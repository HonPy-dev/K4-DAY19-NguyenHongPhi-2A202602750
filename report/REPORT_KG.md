# Báo cáo Day 19 — Flat RAG vs GraphRAG

**Họ tên:** Nguyễn Hồng Phi  **MSSV:** 2A202602750  **Ngày:** 2026-10-05

> Kỳ vọng và thang điểm: `SUBMISSION.md`. Mọi số liệu khớp với `ket_qua_benchmark_kg.txt`. Bản thiết kế ontology nộp riêng ở `report/ONTOLOGY.md`.
> Cấu hình chạy: chat `openrouter:openai/gpt-6-luna`, embedding `openrouter:openai/text-embedding-3-small`, top_k=3, chunk_size=800, 176 chunks, KG 202 nodes / 379 rels.

## 1. Chi phí (10 điểm)

Hai bảng copy từ `ket_qua_benchmark_kg.txt`:

```
== Indexing (one-off)
pipeline  calls    in_tok  out_tok       USD  seconds
flat        176     56072        0   0.00112     97.7
graph       196     91938    12922   0.01117    252.4

== Querying (mean per question)
pipeline  recall  judge   in_tok  out_tok       USD  seconds
flat        0.56   1.33      694      157   0.00014     3.26
graph       0.78   1.50     2925      184   0.00038     3.89
```

| Chỉ số | Flat | Graph | Graph / Flat |
| --- | --- | --- | --- |
| Indexing USD | 0.00112 | 0.01117 | ×10.0 |
| Indexing giây | 97.7 | 252.4 | ×2.6 |
| Indexing calls | 176 | 196 | +20 gọi LLM |
| Mỗi câu: USD | 0.00014 | 0.00038 | ×2.7 |
| Mỗi câu: giây | 3.26 | 3.89 | ×1.2 |
| Mỗi câu: in_tok | 694 | 2925 | ×4.2 |

**Chi phí tăng thêm đến từ đâu?**
> Toàn bộ phần tăng của indexing nằm ở khâu **trích xuất LLM 20 bài báo**: đúng 20 gọi thêm (196 − 176), ~35.9k token đầu vào (prompt trích xuất chứa cả bài + danh sách tên chuẩn) và ~12.9k token đầu ra (JSON các vụ/người/chất), chiếm ~$0.010 trong tổng $0.0112. Phần embedding hai pipeline bằng nhau. Ở lúc trả lời, GraphRAG đắt hơn vì prompt nhồi thêm **dữ kiện graph** bên cạnh top-3 chunk — in_tok gấp 4.2 lần (694 → 2925) chính là phần dữ kiện đó — nên USD/câu ×2.7 và chậm hơn ~0.6 giây/câu. Ước tính hòa vốn: phần xây một lần ($0.010) bằng đúng chi phí hỏi ~72 câu của Flat ($0.00014/câu); về chi phí thuần thì GraphRAG không bao giờ "rẻ lại" (mỗi câu vẫn đắt hơn $0.00024), nó đáng tiền khi **độ chính xác cross-kb** có giá trị lớn hơn chênh lệch này (xem mục 2, 4).

## 2. Từng câu hỏi (10 điểm)

| Câu | Loại | Flat recall / judge | Graph recall / judge | Thắng | Vì sao (1 câu) |
| --- | --- | --- | --- | --- | --- |
| Q1 | single-hop-law | 1.00 / 2 | 1.00 / 2 | Hòa | Định nghĩa "tiền chất" nằm gọn trong một khoản luật, vector search đủ; Graph còn dẫn thêm được "khoản 4 Điều 2 Luật PCMT" |
| Q2 | single-hop-news | 1.00 / 2 | 1.00 / 2 | Hòa | Hai tên bị cáo nằm trong một đoạn tin duy nhất, không cần đi graph |
| Q3 | cross-kb | 0.00 / 0 | 1.00 / 2 | **Graph** | Mức án (tin) và Điều luật + khung phạt (luật) không nằm trong cùng đoạn văn nào; graph đi Person → Case → Crime → Article 251 → Clause 1 |
| Q4 | cross-kb | 0.00 / 0 | 0.00 / 0 | Hòa (cùng hụt) | Câu hỏi mức phạt **tối đa** cần khoản 4 Điều 255 mà bộ lọc khoản của KG-3 không lấy (lỗi E2), Flat thì không retrieve nổi bài tin |
| Q5 | cross-kb-multi-hop | 1.00 / 2 | 1.00 / 2 | Hòa | Chunk tin đã kham đủ số liệu 9,6kg MDMA và cả chunk luật khoản 4 Điều 250 lọt vào top-3 |
| Q6 | aggregation | 0.33 / 2 | 0.67 / 1 | Hòa, mâu thuẫn phép đo (E4) | Graph liệt kê được 3 vụ nhờ cạnh INVOLVES–MDMA (recall 0.67) nhưng judge trừ điểm vì gọi tên vụ khác đáp án chuẩn; Flat paraphrase khéo nên judge chấp nhận dù recall thấp |

**Quy luật:** loại câu hỏi quyết định bên thắng — single-hop thì hai bên hòa (chunk đã chứa đáp án); cross-kb thì graph thắng hoặc hụt ít hơn (Q3 là minh họa gọn nhất: 0 → full điểm); aggregation Depends vào chất lượng chuẩn hóa thực thể; riêng dạng "mức phạt tối đa" thì cả hai gãy vì lỗi lọc ngữ cảnh (E2), không phải vì graph thiếu dữ kiện.

## 3. Phân tích lỗi (20 điểm)

### Lỗi E2: Thiếu ngữ cảnh luật — câu trả lời sai khung hình phạt dù graph có đủ Điều luật

- **Hiện tượng:** Q4 (Hoàng Nato, mức tù tối đa) GraphRAG recall=0.00, judge=0, trả lời không tìm được hành vi lẫn khung phạt, trong khi graph có đầy đủ đường đi tới Điều 255.
- **Bằng chứng 1 — nguyên nhân "bộ lọc khoản":** trích từ file kết quả (Q4 graph): *"Knowledge graph chỉ nêu **Điều 249 BLHS** về tàng trữ trái phép chất ma túy và **Điều 250 BLHS** về vận chuyển trái phép chất ma túy; không liên hệ Hoàng Nato với hành vi nào, và đoạn trích không nêu mức phạt tù tối đa."* — Trong khi Cypher cho thấy Điều 255 (tội "tổ chức sử dụng") có khoản 4 với "tù 20 năm hoặc tù chung thân" (từ khóa `chung thân` của `must_include`):

```cypher
MATCH (a:Article {id:'Điều 255 BLHS'})-[:HAS_CLAUSE]->(cl:Clause)
OPTIONAL MATCH (cl)-[:MENTIONS]->(s:Substance)
RETURN cl.number AS khoản, cl.penalty AS hình_phạt, collect(s.name) AS chất_được_nhắc;
```

```
khoản 1: "phạt tù từ 02 năm đến 07 năm"      chất: []
khoản 2: "phạt tù từ 07 năm đến 15 năm"      chất: []
khoản 3: "phạt tù từ 15 năm đến 20 năm"      chất: []
khoản 4: "phạt tù 20 năm hoặc tù chung thân" chất: []   ← cần nhưng không bao giờ được lấy
```

  Bộ lọc của KG-3 chỉ giữ **khoản 1 hoặc khoản MENTIONS một chất mà vụ INVOLVES** — Điều 255 không nhắc chất nào (tình tiết tăng nặng của nó là hậu quả/hành vi, không phải khối lượng), nên chỉ khoản 1 đi vào ngữ cảnh.
- **Bằng chứng 2 — nguyên nhân "tràn max_facts":** đã tái lập phần retrieve của Q4 bằng cách embed lại toàn bộ corpus (chi phí $0.0011): top-3 chunk cho câu hỏi này là **3 chunk luật** (`blhs-dieu-250`, `blhs-dieu-252`, `blhs-dieu-249`), tức `doc_ids` chỉ chứa node luật. Khi đó `seed_facts` sinh ra hơn 60 cạnh 1-bước chỉ-gồm-tên (mỗi khoản MENTIONS tới 9 chất), chiếm sạch `max_facts=60`, và mọi dữ kiện có nội dung — cạnh `INVOLVED_IN` của Hoàng Nato, text Điều 255 khoản 1 — bị cắt ở bước `facts[:max_facts]`:

```python
g.context(q4, ['blhs-dieu-250','blhs-dieu-252','blhs-dieu-249'])  # doc_ids thật của vector search
# → 60 facts, 100% là cạnh kiểu "(Clause: Điều 249 BLHS khoản 3) -[MENTIONS]-> (Substance: MDMA)", không một text khoản
g.context(q4, [])   # chỉ seed theo tên/biệt danh "Hoàng Nato"
# → 9 facts, có đủ cạnh INVOLVED_IN {charge: 'tổ chức sử dụng...'} và text "[Điều 255 BLHS] khoản 1"
```

  LLM lúc benchmark nhìn thấy đúng cái ngữ cảnh 60-facts-that và trả lời đúng như trích dẫn ở trên ("chỉ nêu Điều 249 và 250").
- **Nguyên nhân:** hai lỗi chồng nhau — (1) quy tắc lọc khoản ở KG-3 giả định mọi khung hình phạt tăng đều gắn với chất cụ thể, sai với tội có tình tiết theo hậu quả/hành vi; (2) thứ tự ghép ngữ cảnh đặt các cạnh tên (ít giá trị) **trước** text khoản (giá trị cao) rồi cùng bị cắt bởi `max_facts`.
- **Đề xuất sửa:** (1) nếu câu hỏi chứa "tối đa/cao nhất" thì bỏ lọc, lấy toàn bộ khoản của Điều đã đi tới — Điều 255 chỉ 5 khoản, tốn thêm ~400 token/câu; (2) đổi thứ tự ưu tiên trong `context()`: append text khoản trước các cạnh seed, hoặc cap riêng seed edges (vd 25) — sửa 1 dòng, không tốn thêm token; (3) lâu dài: mô hình hóa tình tiết tăng nặng/ngưỡng thành property của `Clause` để lọc có chủ đích (đánh đổi: ontology phức tạp hơn, trích xuất khó hơn — đã ghi ở ONTOLOGY.md mục 8).

### Lỗi E4: Phép đo sai — recall và judge mâu thuẫn ở Q6

- **Hiện tượng:** Q6 là câu duy nhất cả hai phép đo chiều ngược nhau: Flat recall=0.33 nhưng judge=2; Graph recall=0.67 nhưng judge=1.
- **Bằng chứng:** trích nguyên văn từ `ket_qua_benchmark_kg.txt` (`must_include` của Q6 = `["Cái Quang Huy", "Lê Minh Thành", "Pháp y tâm thần"]`, gold nêu đúng 3 vụ):
  - Flat (recall 0.33, judge 2): *"- **Vụ kiện hàng Huy gửi:** Giám định xác định các viên nén … là MDMA… - **Vụ Thành mang ma túy đi bán:** 5 viên nén Thành định bán được xác định là MDMA. - **Vụ Đông tại Viện Pháp y tâm thần Trung ương:** … thu giữ 0,686 g MDMA…"* — chỉ khớp đúng 1/3 từ khóa (chữ "Pháp y tâm thần"), hai chỗ còn lại gọi "Huy", "Thành" không đủ chuỗi "Cái Quang Huy"/"Lê Minh Thành", nhưng **đúng đủ 3 vụ về ngữ nghĩa** nên judge cho 2.
  - Graph (recall 0.67, judge 1): *"1. **Vụ vận chuyển hơn 9,6kg MDMA…**: Cái Quang Huy… 2. **Vụ góp 14 triệu đồng mua ma túy tại Hà Nội**: Lê Minh Thành mang 5 viên MDMA đi bán. 3. **Vụ tổ chức sử dụng ma túy tại Sầm Sơn**: … thu 0,686g MDMA tại buồng bệnh của Lê Văn Đông"* — khớp 2/3 từ khóa, và về ngữ nghĩa cũng liệt kê đúng cả 3 vụ (vụ 3 chính là vụ Viện Pháp y tâm thần, chỉ gọi theo địa điểm Sầm Sơn), vậy rating judge=1 là quá chặt.
- **Nguyên nhân:** recall là so chuỗi ký tự cứng — phạt paraphrase đúng; judge là LLM — chấm theo cảm nhận tổng thể và phụ thuộc cách đặt tên vụ việc của answer, nên cùng một câu trả lời đúng mà hai phép đo chấm lệch nhau theo hai hướng. Đây là lỗi của chính **phép đo**, không phải của pipeline.
- **Đề xuất sửa:** (1) `must_include` nên kèm biến thể gọi tên ("Lê Minh Thành"/"Thành") hoặc chấm trên entity đã chuẩn hóa (`link_entity`) thay vì substring; (2) judge nên chấm theo checklist từng ý bắt buộc của gold ("liệt kê đủ 3 vụ nào?") thay vì nhìn tổng thể; (3) judge nên chạy 3 lần rồi lấy mode — temperature=0 đã bật nhưng OpenRouter vẫn có thể route sang backend khác nhau giữa các lần, nên một lượt chấm không ổn định.

### Lỗi E3: Trùng/lệch thực thể — một thứ ngoài đời thành nhiều node

- **Hiện tượng:** node `Substance` chứa nhiều tên cùng chỉ một chất ngoài đời, và một sự kiện thành hai node `Case`.
- **Bằng chứng:**

```cypher
MATCH (s:Substance) RETURN s.name AS tên ORDER BY toLower(tên);
```

```
'Amphetamine', 'Chất ma túy nghi vấn', 'Cocaine', 'cần sa', 'côca', 'etomidate', 'Heroine',
'Ketamine', 'ma túy', 'ma túy tổng hợp', 'ma túy tổng hợp các loại', 'MDMA', 'Methamphetamine',
'thuốc lắc', 'thuốc phiện', 'Tinh thể rắn màu trắng nghi là chất ma túy', 'XLR-11'   ← 17 node
```

  "thuốc lắc" ≈ MDMA/Amphetamine, "ma túy tổng hợp" ≈ Methamphetamine, "côca"/"Cocaine" là hai node song song — none of which khoản luật nào `MENTIONS`, nên các Case đi bằng những node này **không** nối sang luật được.

```cypher
MATCH (k:Case) RETURN k.name, k.doc_id;
```

```
'Vụ phát hiện bao tải nghi chứa 20kg ma túy tại Phú Quốc ngày 27-9' | news-100260927182621527
'Vụ phát hiện kiện hàng nghi chứa 20kg ma túy tại Phú Quốc ngày 25-9' | news-100260927182621527   ← cùng 1 bài
```

- **Nguyên nhân:** nằm ở **thiết kế ontology + prompt trích xuất**, không phải Cypher: khóa định danh là chuỗi tên do LLM tự phát minh, `MERGE` chỉ gộp khi hai chuỗi giống từng ký tự. Với tội danh tôi tránh được điều này vì prompt ép chọn nguyên văn từ danh sách 13 tên chuẩn rồi ép qua `link_entity` (kết quả: đúng 13 node Crime = số tội trong luật); với chất và tên vụ, prompt chỉ "khuyến khích" dùng tên chuẩn nên LLM vẫn mô tả theo ngữ cảnh bài.
- **Đề xuất sửa:** (1) bắt buộc `substances` chọn từ DANH SÁCH CHẤT rồi ép qua `link_entity` với normalize bỏ dấu (giống cách làm với tội danh — trade-off: một số chất lạ như "etomidate" sẽ bị rớt, nhưng chúng vốn không nối được sang luật); (2) gộp sau bằng bảng alias ("thuốc lắc" → MDMA) — thêm ~10 dòng dữ liệu, không tốn token; (3) với `Case`: ràng buộc mẫu đặt tên "Vụ + hành vi + địa điểm" và khử trùng lặp giữa các case cùng `doc_id` bằng so sánh summary (trade-off: thêm một bước so sánh embedding hoặc một lần gọi LLM/bài).

*(Ghi nhận thêm E1 — cầu nối gãy: `MATCH (k:Case) WHERE NOT (k)-[:CHARGED_WITH]->()` trả về 5/16 case; 3 case trong số này **hợp lý** khi không nối (bài rửa tiền Sinaloa — tội ngoài Chương XX; 2 bài "phát hiện nghi vấn" — cơ quan điều tra chưa xác định tội danh), 2 case là bài thu giữ 40kg/20kg mà LLM không khớp nổi tên tội từ văn bản tin — cùng nguyên nhân gốc với E3.)*

## 4. Kết luận (5 điểm)

> Với số liệu của mình: Flat RAG đủ và rẻ hơn 2.7 lần cho câu hỏi **single-hop** (Q1, Q2, Q5 — đáp án nằm gọn trong một đoạn, hai bên hòa điểm, $0.00014 so với $0.00038/câu). Knowledge Graph đáng tiền khi đáp án **rải qua ≥ 2 nguồn** và có một thực thể chuẩn hóa được để nối: trên 3 câu đòi hỏi ghép tin với luật (Q3, Q4, Q6), recall trung bình của Graph là 0.56 so với 0.11 của Flat (nhóm cross-kb thuần Q3–Q5: 0.67 so với 0.33), và Q3 đi từ 0 điểm lên full điểm (judge 0 → 2) nhờ đường Person → Case → Crime → Article — điều không đoạn văn nào chứa được. Điều kiện cụ thể để chọn KG: (1) ≥ 1/3 lượng câu hỏi thuộc loại cross-source; (2) entity cầu nối thuộc tập đóng, chuẩn hóa được (tội danh: 13 tên — được; chất ma túy: không — và E3 là cái giá); (3) chấp nhận chi phí một lần ~$0.010 (bằng ~72 câu hỏi Flat) và đắt hơn $0.00024/câu để mua đúng các câu đó. Ngược lại, với KB tra cứu thuần văn bản pháp quy hoặc số câu hỏi nhỏ, Flat RAG là lựa chọn hợp lý hơn trên cả chi phí lẫn độ trễ.

## 5. Tự kiểm (5 điểm)

```
$ pytest tests/ -q
................................................                         [100%]
48 passed in 0.13s

$ python bench_kg.py --check
[OK] Dữ liệu: 18 điều luật, 20 bài báo
[OK] KG-1 link_entity
[OK] Neo4j kết nối được
[provider] chat = openrouter:openai/gpt-6-luna | embedding = openrouter:openai/text-embedding-3-small
[OK] KG-2 build_graph: 148 node / 294 cạnh, đường xuyên 2 KB dài 2 cạnh
[OK] KG-3 context: 23 dữ kiện, có Điều 251
[OK] KG-4 GraphRAGAgent.answer
[OK] Chi phí check: 1 lần gọi LLM, $0.00100. ...
```

Ảnh Neo4j: `report/img/kg_count.png`, `report/img/kg_cross_kb.png`, `report/img/kg_my_case.png`.
Người đã chọn cho `kg_my_case.png`: **Cái Quang Huy** — truy vấn
`MATCH p=(:Person {name:'Cái Quang Huy'})-[:INVOLVED_IN]->(k:Case)-[:CHARGED_WITH]->(:Crime)<-[:DEFINES]-(:Article) OPTIONAL MATCH q=(k)-[:INVOLVES|LOCATED_IN]->() RETURN p, q`,
Results overview cho thấy Nodes (9): Article 1, Case 2, Crime 1, Location 2, Person 1, Substance 2; Relationships (11): CHARGED_WITH 2, DEFINES 1, INVOLVED_IN 2, INVOLVES 4, LOCATED_IN 2.

## Vấn đề gặp phải (không tính điểm)

> Không có lỗi nào chặn tiến độ. Hai ghi chú nhỏ: (1) session Neo4j Browser tự ngắt vài lần khi thao tác tự động hóa, phải đăng nhập lại — không ảnh hưởng dữ liệu trong graph; (2) đơn giá của `openai/gpt-6-luna` qua OpenRouter là ước tính theo bảng giá khai trong `src/llm.py`, khi báo cáo chính thức cần đối chiếu lại trang giá của provider. Sau khi chạy `--judge`, graph trong Neo4j được giữ nguyên trạng thái (202 nodes / 379 rels) để 3 ảnh chụp khớp với file kết quả benchmark.
