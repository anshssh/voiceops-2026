"""Knowledge-base loading, section chunking and BM25 retrieval.

Chunking rule (from the brief): chunk by section heading, keep the
[SECTION-ID], doc status and effective_from with every chunk.
Retrieval is pure-stdlib BM25 so the agent runs with zero API keys;
an embeddings backend can be dropped in behind the same interface.

Precedence (KB-00.1) is applied as a score multiplier:
current policy > agent guide > help > faq > marketing, and superseded
documents are heavily down-weighted (they are hard negatives by design).
"""
from __future__ import annotations

import csv
import math
import os
import re
from collections import Counter, defaultdict

# Hinglish / Hindi -> English concept expansion for retrieval only.
# Customers say "vapas", documents say "return" - keyword search alone misses this.
EXPANSIONS = {
    "vapas": ["return"], "वापस": ["return"], "लौटाने": ["return"], "लौटा": ["return"],
    "refund": ["refund"], "रिफ़ंड": ["refund"], "रिफंड": ["refund"], "पैसे": ["refund", "money"],
    "cancel": ["cancel"], "कैंसिल": ["cancel"], "रद्द": ["cancel"],
    "kitne": ["how", "many"], "कितने": ["how", "many"], "din": ["days"], "दिन": ["days"],
    "kab": ["when"], "कब": ["when"], "kaise": ["how"], "कैसे": ["how"],
    "hai": [], "kya": [], "क्या": [], "mera": ["my"], "मेरा": ["my"], "mujhe": ["i"],
    "order": ["order"], "ऑर्डर": ["order"], "saman": ["item"], "सामान": ["item"],
    "toota": ["damaged"], "टूटा": ["damaged"], "kharab": ["damaged", "defective"],
    "खराब": ["damaged"], "galat": ["wrong"], "गलत": ["wrong"],
    "delivery": ["delivery"], "डिलीवरी": ["delivery"], "der": ["late"], "देर": ["late"],
    "shikayat": ["report", "complaint"], "शिकायत": ["report"],
    "khola": ["opened"], "खोल": ["opened"], "seal": ["seal"], "सील": ["seal"],
    "milega": ["get"], "मिलेगा": ["get"], "chahiye": ["want"], "चाहिए": ["want"],
    "insaan": ["human"], "इंसान": ["human"], "baat": ["talk"], "बात": ["talk"],
    "sahayak": ["assistant"], "ticket": ["ticket"], "टिकट": ["ticket"],
}

PRECEDENCE_BOOST = {"policy": 1.45, "agent_guide": 1.25, "help": 1.1,
                    "faq": 0.9, "marketing": 0.65, "meta": 1.0}

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    toks = TOKEN_RE.findall(text.lower())
    out = []
    for tok in toks:
        out.append(tok)
        out.extend(EXPANSIONS.get(tok, []))
    return out


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    meta = {}
    body = raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            for line in raw[3:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = raw[end + 4:]
    return meta, body


class Chunk:
    __slots__ = ("section_id", "doc_id", "doc_type", "status", "title", "text", "tokens")

    def __init__(self, section_id, doc_id, doc_type, status, title, text):
        self.section_id = section_id
        self.doc_id = doc_id
        self.doc_type = doc_type
        self.status = status
        self.title = title
        self.text = text
        self.tokens = tokenize(title + " " + text)


class KnowledgeBase:
    def __init__(self, kb_dir: str, data_dir: str | None = None):
        self.chunks: list[Chunk] = []
        self.by_section: dict[str, Chunk] = {}
        for fname in sorted(os.listdir(kb_dir)):
            if not fname.endswith(".md"):
                continue
            with open(os.path.join(kb_dir, fname), encoding="utf-8") as fh:
                meta, body = parse_frontmatter(fh.read())
            # split on section headings: ## [ID] Title
            parts = re.split(r"^## \[([A-Z0-9.\-]+)\]\s*(.*)$", body, flags=re.M)
            # parts: [pre, id, title, text, id, title, text, ...]
            for i in range(1, len(parts) - 2, 3):
                sec_id, title, text = parts[i], parts[i + 1].strip(), parts[i + 2].strip()
                chunk = Chunk(sec_id, meta.get("doc_id", fname), meta.get("doc_type", ""),
                              meta.get("status", "current"), title, text)
                self.chunks.append(chunk)
                self.by_section[sec_id] = chunk
        # Product catalog rows act as retrievable evidence: products.csv:SKU
        self.products: dict[str, dict] = {}
        if data_dir:
            ppath = os.path.join(data_dir, "products.csv")
            if os.path.exists(ppath):
                with open(ppath, encoding="utf-8") as fh:
                    for row in csv.DictReader(fh):
                        self.products[row["sku"]] = row
                        text = (f"{row['title']} brand {row['brand']} category {row['return_category']} "
                                f"price {row['price_inr']} rupees fulfilled by {row['fulfilled_by']} "
                                f"assured {row['assured']} warranty {row['warranty_months']} months")
                        chunk = Chunk(f"products.csv:{row['sku']}", "products.csv", "catalog",
                                      "current", row["title"], text)
                        self.chunks.append(chunk)
                        self.by_section[chunk.section_id] = chunk
        self._build_index()

    def _build_index(self):
        self.df: Counter = Counter()
        self.doc_len: list[int] = []
        for chunk in self.chunks:
            self.doc_len.append(len(chunk.tokens))
            for tok in set(chunk.tokens):
                self.df[tok] += 1
        self.avg_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 1.0
        self.tf: list[Counter] = [Counter(c.tokens) for c in self.chunks]

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        qtoks = tokenize(query)
        if not qtoks:
            return []
        n = len(self.chunks)
        k1, b = 1.5, 0.75
        scores = defaultdict(float)
        for tok in set(qtoks):
            df = self.df.get(tok, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for idx, chunk in enumerate(self.chunks):
                f = self.tf[idx].get(tok, 0)
                if not f:
                    continue
                denom = f + k1 * (1 - b + b * self.doc_len[idx] / self.avg_len)
                scores[idx] += idf * f * (k1 + 1) / denom
        ranked = []
        for idx, score in scores.items():
            chunk = self.chunks[idx]
            boost = PRECEDENCE_BOOST.get(chunk.doc_type, 1.0)
            if chunk.status == "superseded":
                boost *= 0.25
            ranked.append((chunk, score * boost))
        ranked.sort(key=lambda x: -x[1])
        return ranked[:top_k]

    def find_product(self, text: str) -> dict | None:
        """Product mentioned by SKU, or by (partial) title in the text."""
        m = re.search(r"\b([A-Z]{3}-\d{4})\b", text.upper())
        if m and m.group(1) in self.products:
            return self.products[m.group(1)]
        def norm(s: str) -> str:
            return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()
        low = norm(text)
        best, best_len = None, 0
        for sku, row in self.products.items():
            # title without colour variant, e.g. 'UrbanThread Slim Fit Jeans';
            # punctuation-insensitive so ASR text ('Notebook Pack of 4',
            # no parentheses) still matches the catalog title
            base = norm(row["title"].split(",")[0])
            if base and base in low and len(base) > best_len:
                best, best_len = row, len(base)
        return best
