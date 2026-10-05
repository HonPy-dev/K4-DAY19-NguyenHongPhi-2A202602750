"""Knowledge Graph (Neo4j) + GraphRAG over two drug-topic knowledge bases.

Contract (fixed — bench_kg.py and the tests rely on it):
    link_entity(name, known)                       -> one of `known` or None          (TODO KG-1)
    build_graph(graph, law_docs, news_docs, llm_fn)   load both KBs into Neo4j      (TODO KG-2)
        every node created from ONE document carries the property `doc_id`
    Neo4jGraph.context(question, doc_ids)         -> list[str] facts               (TODO KG-3)
    GraphRAGAgent.answer(question, top_k)         -> str                           (TODO KG-4)

Everything else in this file is a HINT: one possible ontology (below). Use it as is, change it,
or design your own — your own ontology + report/ONTOLOGY.md earns the bonus (see SUBMISSION.md).

Suggested ontology (Crime is the bridge between the law KB and the news KB):

    (:Article {id, title, law, doc_id})-[:DEFINES]->(:Crime {name})
    (:Article)-[:HAS_CLAUSE]->(:Clause {id, number, penalty, text})-[:MENTIONS]->(:Substance {name})
    (:Case {name, summary, date, doc_id})-[:CHARGED_WITH]->(:Crime)
    (:Case)-[:INVOLVES {amount}]->(:Substance)
    (:Case)-[:LOCATED_IN]->(:Location {name})
    (:Person {name, aliases})-[:INVOLVED_IN {role, sentence, charge}]->(:Case)
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any, Callable

from .models import Document
from .store import EmbeddingStore

# Canonical substance names: the ones BLHS Chương XX lists, plus common ones in Vietnamese news.
SUBSTANCES = ["Heroine", "Cocaine", "Methamphetamine", "Amphetamine", "MDMA", "XLR-11", "Ketamine",
              "cần sa", "thuốc phiện", "côca"]
CLAUSE_START = re.compile(r"^(\d+)\.\s", re.MULTILINE)
FOOTNOTE = re.compile(r"\[\d+\]")

def load_markdown_docs(folder: str | Path) -> list[Document]:
    """Read crawler output (.md with a flat `key: "value"` front matter) into Documents."""
    docs = []
    for path in sorted(Path(folder).glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        _, front, body = raw.split("---", 2)
        metadata = {k: json.loads(v) for k, v in re.findall(r'^(\w+): (".*")$', front, re.MULTILINE)}
        docs.append(Document(id=metadata.get("doc_id", path.stem), content=body.strip(), metadata=metadata))
    return docs

def normalize_crime(name: str) -> str:
    """'Tội Mua bán trái phép chất ma túy' -> 'mua bán trái phép chất ma túy'."""
    name = re.sub(r"\s+", " ", name.strip().strip("\"'“”").lower())
    return name.removeprefix("tội ").strip()

def link_entity(name: str, known: list[str], normalize: Callable[[str], str] = normalize_crime) -> str | None:
    """Map a free-text mention (e.g. a charge written by a journalist) onto one canonical name in `known`."""
    target = normalize(name)
    if not target:
        return None
    by_normalized: dict[str, str] = {}
    for original in known:
        by_normalized.setdefault(normalize(original), original)   # keep the original spelling of `known`
    if target in by_normalized:
        return by_normalized[target]
    close = difflib.get_close_matches(target, list(by_normalized), n=1, cutoff=0.8)
    return by_normalized[close[0]] if close else None

def find_substances(text: str) -> list[str]:
    lowered = text.lower()
    return [name for name in SUBSTANCES if name.lower() in lowered]

# ----------------------------------------------------------------------------------------------
# Ontology v2 — structured thresholds + substance canonicalization (bonus, see report/ONTOLOGY.md)
# ----------------------------------------------------------------------------------------------

def _to_grams(number: str, unit: str) -> float:
    """'9,6' + 'kg' -> 9600.0. Handles '1.000' thousand dots and ',' decimal comma."""
    value = float(number.replace(".", "").replace(",", "."))
    return value * 1000.0 if unit.startswith(("k", "K")) else value

# Ordered: the "đến dưới" variant must win before the plain "đến" one.
AMOUNT_RANGES = [
    re.compile(r"từ\s+([\d.,]+)\s*(gam|kilôgam|kg)\s+đến\s+dưới\s+([\d.,]+)\s*(gam|kilôgam|kg)"),
    re.compile(r"từ\s+([\d.,]+)\s*(gam|kilôgam|kg)\s+đến\s+([\d.,]+)\s*(gam|kilôgam|kg)"),
    re.compile(r"([\d.,]+)\s*(gam|kilôgam|kg)\s+trở\s+lên"),
    re.compile(r"dưới\s+([\d.,]+)\s*(gam|kilôgam|kg)"),
]
LAW_POINTS = re.compile(r"(?:^|(?<=\s))([abcdđeeghik])\)\s")
AMOUNT_IN_TEXT = re.compile(r"([\d.,]+)\s*(kg|kilôgam|gam|gr|g)\b")
CANONICAL_SUBSTANCES = {s.lower() for s in SUBSTANCES}
SUBSTANCE_ALIASES = {
    "thuốc lắc": "MDMA", "ma túy tổng hợp": "Methamphetamine", "ma túy đá": "Methamphetamine",
    "đá": "Methamphetamine", "bóng": "Heroine", "hê rô-in": "Heroine", "hêrôin": "Heroine",
    "coke": "Cocaine", "cỏ": "cần sa", " cần sa khô": "cần sa",
}

def substance_range(text: str) -> tuple[float, float] | None:
    """'từ 05 gam đến dưới 30 gam' -> (5.0, 30.0); '100 gam trở lên' -> (100.0, None)."""
    for pattern in AMOUNT_RANGES:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groups()
        if len(groups) == 4:                                   # từ X ... đến (dưới) Y
            return _to_grams(groups[0], groups[1]), _to_grams(groups[2], groups[3])
        if "trở lên" in match.group(0):                        # X gam trở lên
            return _to_grams(groups[0], groups[1]), None
        return 0.0, _to_grams(groups[0], groups[1])            # dưới X gam
    return None

def parse_penalty_years(penalty: str) -> tuple[int | None, int | None]:
    """'phạt tù từ 02 năm đến 07 năm' -> (2, 7); chung thân -> 99; tử hình -> 100 (numeric proxies)."""
    span = re.search(r"từ\s+(\d+)\s+năm\s+đến\s+(\d+)\s+năm", penalty)
    if span:
        low, high = int(span.group(1)), int(span.group(2))
    else:
        single = re.search(r"(\d+)\s+năm", penalty)
        low = int(single.group(1)) if single else None
        high = low
    if "tử hình" in penalty:
        high = 100
    elif "chung thân" in penalty:
        high = 99
    return low, high

def clause_ranges(text: str) -> list[dict]:
    """Per law point (điểm a), b)…): every substance mentioned with its numeric weight range.

    Substances named in the same point as the range share it: 'Heroine, Cocaine, … MDMA hoặc
    XLR-11 có khối lượng từ 05 gam đến dưới 30 gam'.
    """
    pieces = [(m.start(), m.group(1)) for m in LAW_POINTS.finditer(text)]
    pieces.append((len(text), ""))
    ranges = []
    for index in range(len(pieces) - 1):
        segment = text[pieces[index][0]:pieces[index + 1][0]]
        span = substance_range(segment)
        if not span:
            continue
        for name in find_substances(segment):
            ranges.append({"substance": name, "min_g": span[0], "max_g": span[1]})
    return ranges

def normalize_substance(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().strip("\"'“”").lower())

def link_substance(name: str) -> str:
    """Map a free-text substance mention onto a canonical name (alias first, then fuzzy)."""
    target = normalize_substance(name)
    if not target:
        return name
    for canonical in SUBSTANCES:
        if normalize_substance(canonical) == target:
            return canonical
    if target in SUBSTANCE_ALIASES:
        return SUBSTANCE_ALIASES[target]
    close = difflib.get_close_matches(target, sorted(CANONICAL_SUBSTANCES), n=1, cutoff=0.8)
    if close:
        for canonical in SUBSTANCES:
            if normalize_substance(canonical) == close[0]:
                return canonical
    return name                                              # unresolved — keep, but flag canonical=false

def amount_in_grams(amount: str) -> float | None:
    """'hơn 9,6 kg' -> 9600.0; 'khoảng 406 g' -> 406.0; '5 viên' -> None."""
    match = AMOUNT_IN_TEXT.search((amount or "").lower())
    return _to_grams(match.group(1), match.group(2)) if match else None

# ----------------------------------------------------------------------------------------------
# HINT — suggested ontology: extraction helpers
# ----------------------------------------------------------------------------------------------

def parse_law_article(doc: Document) -> dict[str, Any]:
    """Deterministic (regex) extraction for one 'Điều' — law text is regular enough to skip the LLM."""
    article_id = doc.metadata["article"]                       # "Điều 251 BLHS"
    title = doc.metadata["title"].split(". ", 1)[-1]           # "Tội mua bán trái phép chất ma túy"
    body = FOOTNOTE.sub("", doc.content)
    starts = list(CLAUSE_START.finditer(body))
    clauses = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(body)
        text = body[start.start():end].strip()
        first_line = text.splitlines()[0]
        penalty = re.search(r"\bbị ((?:phạt|tù|cảnh cáo).+?)(?::|$)", first_line)
        clauses.append({
            "id": f"{article_id} khoản {start.group(1)}",
            "number": int(start.group(1)),
            "penalty": penalty.group(1).rstrip(".") if penalty else "",
            "text": text,
            "substances": find_substances(text),
        })
    for clause in clauses:
        clause["penalty_min_years"], clause["penalty_max_years"] = parse_penalty_years(clause["penalty"])
        clause["ranges"] = clause_ranges(clause["text"])
    return {
        "id": article_id,
        "law": doc.metadata.get("law", ""),
        "title": title,
        "doc_id": doc.id,
        "crime": normalize_crime(title) if title.startswith("Tội ") else None,
        "clauses": clauses,
    }

NEWS_EXTRACTION_PROMPT = """Bạn trích xuất knowledge graph từ một bài báo tiếng Việt về ma túy.
Chỉ dùng thông tin có trong bài. Trả về JSON đúng dạng:
{{"cases": [{{
  "name": "tên ngắn của vụ việc, ví dụ: Vụ mua bán 36kg ma túy tại TP.HCM",
  "summary": "1-2 câu tóm tắt",
  "date": "ngày xảy ra/xét xử nếu có, dạng YYYY-MM-DD hoặc chuỗi rỗng",
  "location": "tỉnh/thành phố, chuỗi rỗng nếu không rõ",
  "charges": ["tội danh, BẮT BUỘC chọn đúng nguyên văn từ DANH SÁCH TỘI DANH"],
  "substances": [{{"name": "tên chất, dùng tên chuẩn trong DANH SÁCH CHẤT nếu khớp", "amount": "khối lượng nếu có"}}],
  "people": [{{"name": "họ tên", "aliases": ["biệt danh"], "role": "bị cáo|bị can|nghi phạm|người liên quan|cán bộ",
               "charge": "tội danh của người này (từ DANH SÁCH TỘI DANH) hoặc chuỗi rỗng",
               "sentence": "mức án nếu có, ví dụ: tử hình, 8 năm tù"}}]
}}]}}
Bài không nói về vụ việc cụ thể (tuyên truyền, hội nghị...) thì trả về {{"cases": []}}.

DANH SÁCH TỘI DANH: {crimes}
DANH SÁCH CHẤT: {substances}

Tiêu đề: {title}
Nội dung:
{content}"""

def extract_news_cases(doc: Document, llm_fn: Callable[[str], str], known_crimes: list[str]) -> list[dict]:
    """LLM extraction for one news article; charges are re-linked to law-KB crimes in code."""
    prompt = NEWS_EXTRACTION_PROMPT.format(
        crimes="; ".join(known_crimes), substances=", ".join(SUBSTANCES),
        title=doc.metadata.get("title", ""), content=doc.content[:12000],
    )
    try:
        cases = json.loads(llm_fn(prompt)).get("cases", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    for case in cases:
        case["charges"] = sorted({c for c in (link_entity(x, known_crimes) for x in case.get("charges", [])) if c})
        for person in case.get("people", []):
            person["charge"] = link_entity(person.get("charge") or "", known_crimes) or ""
        for substance in case.get("substances", []):
            linked = link_substance(substance.get("name") or "")
            substance["name"] = linked
            substance["canonical"] = linked.lower() in CANONICAL_SUBSTANCES
            substance["amount_g"] = amount_in_grams(substance.get("amount") or "")
    return cases

# ----------------------------------------------------------------------------------------------
# Neo4j
# ----------------------------------------------------------------------------------------------

class Neo4jGraph:
    """Thin wrapper over the official neo4j driver."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        from neo4j import GraphDatabase

        self.driver = GraphDatabase.driver(uri, auth=(user, password), notifications_min_severity="OFF")
        self.driver.verify_connectivity()

    def close(self) -> None:
        self.driver.close()

    def run(self, cypher: str, **params: Any) -> list[dict]:
        records, _, _ = self.driver.execute_query(cypher, params)
        return [record.data() for record in records]

    def reset(self) -> None:
        """Delete every node, relationship and constraint (bench_kg.py calls this before build_graph)."""
        self.run("MATCH (n) DETACH DELETE n")
        for row in self.run("SHOW CONSTRAINTS YIELD name RETURN name"):
            self.run(f"DROP CONSTRAINT `{row['name']}` IF EXISTS")

    def stats(self) -> dict[str, int]:
        nodes = self.run("MATCH (n) RETURN count(n) AS n")[0]["n"]
        rels = self.run("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
        return {"nodes": nodes, "relationships": rels}

    def seed_facts(self, question: str, doc_ids: list[str], skip_labels: tuple[str, ...] = (),
                   limit: int = 60) -> tuple[list[str], list[str]]:
        """Ontology-independent first step: seed nodes + their 1-hop edges as text facts.

        Seeds = nodes whose `doc_id` is in doc_ids, or whose `name`/`aliases` appear in the question.
        Returns (seed elementIds, facts). Nodes with a label in skip_labels are left out of the facts.
        """
        seeds = self.run(
            """
            MATCH (n)
            WHERE n.doc_id IN $doc_ids
               OR (n.name IS :: STRING AND size(n.name) >= 3 AND toLower($q) CONTAINS toLower(n.name))
               OR any(a IN coalesce(n.aliases, []) WHERE size(a) >= 3 AND toLower($q) CONTAINS toLower(a))
            RETURN elementId(n) AS id
            """,
            q=question, doc_ids=doc_ids,
        )
        seed_ids = [row["id"] for row in seeds]
        edges = self.run(
            """
            MATCH (s)-[r]-(m)
            WHERE elementId(s) IN $ids
              AND none(l IN labels(s) + labels(m) WHERE l IN $skip)
            WITH DISTINCT r LIMIT $limit
            WITH startNode(r) AS a, r, endNode(r) AS b
            RETURN labels(a)[0] AS a_label, coalesce(a.name, a.id) AS a_name, type(r) AS rel,
                   properties(r) AS props, labels(b)[0] AS b_label, coalesce(b.name, b.id) AS b_name
            """,
            ids=seed_ids, skip=list(skip_labels), limit=limit,
        )
        facts = []
        for e in edges:
            props = ", ".join(f"{k}: {v}" for k, v in e["props"].items() if v)
            facts.append(f"({e['a_label']}: {e['a_name']}) -[{e['rel']}{' {' + props + '}' if props else ''}]-> "
                         f"({e['b_label']}: {e['b_name']})")
        return seed_ids, facts

    # ---------------------------------------------------------------- HINT — suggested ontology: writes

    def suggested_constraints(self) -> None:
        for label, key in [("Article", "id"), ("Clause", "id"), ("Crime", "name"), ("Case", "name"),
                           ("Substance", "name"), ("Person", "name"), ("Location", "name")]:
            self.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")

    def add_law_article(self, article: dict) -> None:
        self.run(
            """
            MERGE (a:Article {id: $id}) SET a.title = $title, a.law = $law, a.doc_id = $doc_id
            FOREACH (crime IN CASE WHEN $crime IS NULL THEN [] ELSE [$crime] END |
                MERGE (c:Crime {name: crime}) MERGE (a)-[:DEFINES]->(c))
            WITH a
            UNWIND $clauses AS clause
            MERGE (cl:Clause {id: clause.id})
              SET cl.number = clause.number, cl.penalty = clause.penalty, cl.text = clause.text, cl.doc_id = $doc_id,
                  cl.penalty_min_years = clause.penalty_min_years, cl.penalty_max_years = clause.penalty_max_years
            MERGE (a)-[:HAS_CLAUSE]->(cl)
            FOREACH (s IN clause.substances | MERGE (sub:Substance {name: s}) MERGE (cl)-[:MENTIONS]->(sub))
            FOREACH (r IN clause.ranges | MERGE (sub:Substance {name: r.substance})
                MERGE (cl)-[at:APPLIES_TO]->(sub) SET at.min_g = r.min_g, at.max_g = r.max_g)
            """,
            **article,
        )

    def add_news_case(self, case: dict, doc: Document) -> None:
        self.run(
            """
            MERGE (k:Case {name: $name})
              SET k.summary = $summary, k.date = $date, k.doc_id = $doc_id, k.source_title = $title
            FOREACH (loc IN CASE WHEN $location = '' THEN [] ELSE [$location] END |
                MERGE (l:Location {name: loc}) MERGE (k)-[:LOCATED_IN]->(l))
            FOREACH (crime IN $charges | MERGE (c:Crime {name: crime}) MERGE (k)-[:CHARGED_WITH]->(c))
            FOREACH (s IN $substances | MERGE (sub:Substance {name: s.name})
                SET sub.canonical = s.canonical
                MERGE (k)-[r:INVOLVES]->(sub) SET r.amount = s.amount, r.amount_g = s.amount_g)
            FOREACH (p IN $people | MERGE (person:Person {name: p.name})
                SET person.aliases = coalesce(p.aliases, [])
                MERGE (person)-[r:INVOLVED_IN]->(k) SET r.role = p.role, r.charge = p.charge, r.sentence = p.sentence)
            """,
            name=case.get("name") or doc.metadata.get("title", doc.id),
            summary=case.get("summary", ""), date=case.get("date", ""), location=case.get("location", ""),
            charges=case.get("charges", []), people=[p for p in case.get("people", []) if p.get("name")],
            substances=[s for s in case.get("substances", []) if s.get("name")],
            doc_id=doc.id, title=doc.metadata.get("title", ""),
        )

    # ---------------------------------------------------------------- KG-3

    def context(self, question: str, doc_ids: list[str], max_facts: int = 60) -> list[str]:
        """Graph facts for a question: seeds + 1 hop, then the legal basis of every case reached.

        v2 (own ontology): keeps only text-bearing facts when the budget is tight, matches case
        amounts against structured APPLIES_TO thresholds, and answers "mức phạt tối đa" questions
        by ranking clauses on penalty_max_years.
        """
        seed_ids, seed_edge_facts = self.seed_facts(question, doc_ids)
        wants_max = bool(re.search(r"tối đa|cao nhất|nặng nhất|chung thân|tử hình", question.lower()))
        facts: list[str] = []

        # Vụ việc là seed hoặc kề một seed (Person -> Case, ...)
        cases = self.run(
            """
            MATCH (k:Case)
            WHERE elementId(k) IN $ids OR EXISTS { MATCH (s)--(k) WHERE elementId(s) IN $ids }
            RETURN elementId(k) AS id, k.name AS name, k.summary AS summary
            """,
            ids=seed_ids,
        )
        for case in cases:
            facts.append(f"Vụ việc '{case['name']}': {case['summary']}")
        case_ids = [case["id"] for case in cases]

        # Cầu nối sang KB luật: (Case)-[:CHARGED_WITH]->(Crime)<-[:DEFINES]-(Article)-[:HAS_CLAUSE]->(Clause)
        # Giữ khoản 1 (khung cơ bản) + các khoản nhắc tới chất mà chính vụ đó INVOLVES.
        clauses = self.run(
            """
            MATCH (k:Case)-[:CHARGED_WITH]->(:Crime)<-[:DEFINES]-(a:Article)-[:HAS_CLAUSE]->(cl:Clause)
            WHERE elementId(k) IN $ids
              AND (cl.number = 1 OR EXISTS { MATCH (k)-[:INVOLVES]->(s:Substance)<-[:MENTIONS]-(cl) })
            RETURN a.id AS article, a.title AS title, cl.number AS number, cl.text AS text
            ORDER BY article, number
            """,
            ids=case_ids,
        )

        # v2: khớp ngưỡng bằng số — vụ INVOLVES amount_g nằm trong khoảng APPLIES_TO của khoản
        thresholds = self.run(
            """
            MATCH (k:Case)-[inv:INVOLVES]->(s:Substance)<-[at:APPLIES_TO]-(cl:Clause)<-[:HAS_CLAUSE]-(a:Article)
            WHERE elementId(k) IN $ids AND inv.amount_g IS NOT NULL
              AND inv.amount_g >= at.min_g AND (at.max_g IS NULL OR inv.amount_g < at.max_g)
            RETURN a.id AS article, a.title AS title, cl.number AS number, cl.text AS text,
                   s.name AS substance, inv.amount AS amount, inv.amount_g AS amount_g,
                   at.min_g AS min_g, at.max_g AS max_g
            ORDER BY article, number
            """,
            ids=case_ids,
        )

        # v2: câu hỏi về mức phạt tối đa -> khoản có khung cao nhất của từng Điều đi tới được
        if wants_max:
            clauses += self.run(
                """
                MATCH (k:Case)-[:CHARGED_WITH]->(:Crime)<-[:DEFINES]-(a:Article)-[:HAS_CLAUSE]->(cl:Clause)
                WHERE elementId(k) IN $ids AND cl.penalty_max_years IS NOT NULL
                WITH a, cl ORDER BY cl.penalty_max_years DESC
                WITH a, collect(cl)[..1] AS top
                UNWIND top AS cl
                RETURN a.id AS article, a.title AS title, cl.number AS number, cl.text AS text
                """,
                ids=case_ids,
            )

        # Câu hỏi nhắc thẳng một Điều ("Điều 251") -> lấy khoản 1 + khoản nhắc chất có trong câu hỏi;
        # nếu hỏi mức tối đa thì lấy khoản có khung cao nhất của Điều đó.
        for number in dict.fromkeys(re.findall(r"[Đđ]iều (\d+)", question)):
            if wants_max:
                rows = self.run(
                    """
                    MATCH (a:Article)-[:HAS_CLAUSE]->(cl:Clause)
                    WHERE a.id STARTS WITH ($prefix + ' ') AND cl.penalty_max_years IS NOT NULL
                    WITH a, cl ORDER BY cl.penalty_max_years DESC
                    WITH a, collect(cl)[..1] AS top UNWIND top AS cl
                    RETURN a.id AS article, a.title AS title, cl.number AS number, cl.text AS text
                    """,
                    prefix=f"Điều {number}",
                )
            else:
                rows = self.run(
                    """
                    MATCH (a:Article)-[:HAS_CLAUSE]->(cl:Clause)
                    WHERE a.id STARTS WITH ($prefix + ' ')
                      AND (cl.number = 1 OR EXISTS {
                            MATCH (cl)-[:MENTIONS]->(s:Substance) WHERE s.name IN $subs })
                    RETURN a.id AS article, a.title AS title, cl.number AS number, cl.text AS text
                    ORDER BY article, number
                    """,
                    prefix=f"Điều {number}", subs=find_substances(question),
                )
            clauses += rows

        for row in clauses:
            facts.append(f"[{row['article']} - {row['title']}] khoản {row['number']}: {row['text']}")
        for row in thresholds:
            span = (f"từ {row['min_g']:.0f} gam"
                    if row["max_g"] is None else f"từ {row['min_g']:.0f} đến dưới {row['max_g']:.0f} gam")
            facts.append(f"[{row['article']}] vụ '{row['amount']}' {row['substance']} ≈ {row['amount_g']:.0f} gam "
                         f"→ rơi vào ngưỡng {span} của khoản {row['number']}")

        # Ưu tiên dữ kiện có nội dung (vụ + khoản luật + ngưỡng) trước các cạnh chỉ có tên;
        # khi vượt max_facts thì cắt phần cạnh seed ở cuối, không cắt text khoản luật.
        facts += seed_edge_facts
        return list(dict.fromkeys(facts))[:max_facts]

# ---------------------------------------------------------------------------------------------- KG-2

def build_graph(graph: Neo4jGraph, law_docs: list[Document], news_docs: list[Document],
                llm_fn: Callable[..., str]) -> None:
    """Load both KBs into an empty graph. llm_fn(prompt, json_mode=False) -> str (metered OpenAI chat)."""
    # TODO KG-2: create YOUR ontology in Neo4j from both KBs.
    #   Contract: every node created from one document has the property doc_id = Document.id.
    #   Fastest start: the HINT helpers above (parse_law_article, extract_news_cases, suggested_constraints,
    #   add_law_article, add_news_case). Own ontology + report/ONTOLOGY.md = bonus (SUBMISSION.md).
    graph.suggested_constraints()

    # KB luật: regex, deterministic
    articles = [parse_law_article(d) for d in law_docs]
    for article in articles:
        graph.add_law_article(article)

    # KB tin: LLM extraction, tội danh được link về tên chuẩn trong luật qua link_entity
    crimes = [a["crime"] for a in articles if a["crime"]]
    for doc in news_docs:
        for case in extract_news_cases(doc, lambda p: llm_fn(p, json_mode=True), crimes):
            graph.add_news_case(case, doc)

# ---------------------------------------------------------------------------------------------- KG-4

GRAPH_PROMPT = """Trả lời câu hỏi chỉ dựa trên ngữ cảnh (đoạn văn bản và dữ kiện từ knowledge graph).
Nêu rõ số Điều luật khi có. Nếu ngữ cảnh không đủ, nói không đủ thông tin.

Dữ kiện knowledge graph:
{facts}

Đoạn văn bản:
{chunks}

Câu hỏi: {question}
Trả lời:"""

class GraphRAGAgent:
    """Hybrid GraphRAG: the same vector top-k as flat RAG, plus facts expanded from the graph."""

    def __init__(self, store: EmbeddingStore, graph: Neo4jGraph, llm_fn: Callable[[str], str]) -> None:
        self.store = store
        self.graph = graph
        self.llm_fn = llm_fn

    def answer(self, question: str, top_k: int = 3) -> str:
        chunks = self.store.search(question, top_k=top_k)
        doc_ids = list(dict.fromkeys(chunk["metadata"]["doc_id"] for chunk in chunks))
        facts = self.graph.context(question, doc_ids)
        prompt = GRAPH_PROMPT.format(
            facts="\n".join(f"- {fact}" for fact in facts),
            chunks="\n\n".join(f"[{i}] {chunk['content']}" for i, chunk in enumerate(chunks, start=1)),
            question=question,
        )
        return self.llm_fn(prompt)
