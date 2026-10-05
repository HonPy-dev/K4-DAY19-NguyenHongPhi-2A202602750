# Báo cáo Day 19 — Flat RAG vs GraphRAG

**Họ tên:** Nguyễn Hồng Phi  **MSSV:** 2A202602750  **Ngày:** 2026-10-05

> Kỳ vọng và thang điểm: `SUBMISSION.md`. Mọi số liệu ở mục 1, 2, 4 khớp với `ket_qua_benchmark_kg.txt` (ontology **tự thiết kế v2** — `src/graph.py`). Ontology gợi ý đã chạy benchmark riêng để so sánh trước/sau, kết quả lưu tại `ket_qua_benchmark_kg.hint.txt`; phần phân tích lỗi (mục 3) dùng file này làm bằng chứng "trước" khi cần. Thiết kế ontology: `report/ONTOLOGY.md` (mục 7 là bảng so sánh với gợi ý).
> Cấu hình chạy: chat `openrouter:openai/gpt-6-luna`, embedding `openrouter:openai/text-embedding-3-small`, top_k=3, chunk_size=800, 176 chunks, KG 199 nodes / 529 rels.

## 1. Chi phí (10 điểm)

Hai bảng copy từ `ket_qua_benchmark_kg.txt`:

```
== Indexing (one-off)
pipeline  calls    in_tok  out_tok       USD  seconds
flat        176     56072        0   0.00112    102.0
graph       196     91938    13772   0.01159    270.8

== Querying (mean per question)
pipeline  recall  judge   in_tok  out_tok       USD  seconds
flat        0.50   1.17      694      139   0.00013     3.08
graph       1.00   1.83     5273      243   0.00064     4.18
```

| Chỉ số | Flat | Graph | Graph / Flat |
| --- | --- | --- | --- |
| Indexing USD | 0.00112 | 0.01159 | ×10.3 |
| Indexing giây | 102.0 | 270.8 | ×2.7 |
| Indexing calls | 176 | 196 | +20 gọi LLM |
| Mỗi câu: USD | 0.00013 | 0.00064 | ×4.9 |
| Mỗi câu: giây | 3.08 | 4.18 | ×1.4 |
| Mỗi câu: in_tok | 694 | 5273 | ×7.6 |

**Chi phí tăng thêm đến từ đâu?**
> Indexing: toàn bộ phần tăng là **20 lần gọi LLM trích xuất 20 bài tin** (~35.9k token vào, ~13.8k token ra, ~$0.0105) — phần embedding hai pipeline bằng nhau. Đáng chú ý: ontology v2 **không đắt hơn v1 ở khâu này** dù thêm parser ngưỡng/khung phạt vì toàn bộ là regex (0 token); output LLM tăng nhẹ (13.8k so với 12.9k) chỉ do biến thiên của LLM giữa hai lần chạy. Lúc trả lời: prompt GraphRAG nhồi thêm dữ kiện graph nên in_tok gấp 7.6 lần (694 → 5273), USD/câu ×4.9 (+$0.00051), chậm hơn ~1.1 giây/câu; v2 đắt hơn v1 ở mục này ($0.00064 so với $0.00038) vì ngữ cảnh giờ giữ được nhiều text khoản luật hơn (xem mục 3, E2) — trả tiền cho đúng dữ kiện thay vì các cạnh tên rỗng. Hòa vốn: phần xây một lần $0.0116 bằng chi phí hỏi ~89 câu của Flat ($0.00013/câu); mua được gì: recall trung bình 0.50 → 1.00 và judge 1.17 → 1.83.

## 2. Từng câu hỏi (10 điểm)

| Câu | Loại | Flat recall / judge | Graph recall / judge | Thắng | Vì sao (1 câu) |
| --- | --- | --- | --- | --- | --- |
| Q1 | single-hop-law | 1.00 / 2 | 1.00 / 2 | Hòa | Định nghĩa "tiền chất" nằm gọn trong một khoản luật; Graph chỉ hơn ở việc dẫn đúng "khoản 4 Điều 2" |
| Q2 | single-hop-news | 1.00 / 2 | 1.00 / 2 | Hòa | Hai bị cáo nằm trong một đoạn tin duy nhất |
| Q3 | cross-kb | 0.00 / 0 | 1.00 / 2 | **Graph** | Mức án (tin) và Điều luật + khung phạt (luật) không cùng đoạn văn; graph đi Person → Case → Crime → Điều 251 khoản 1 |
| Q4 | cross-kb | 0.00 / 0 | 1.00 / 2 | **Graph** | "Mức phạt tối đa" cần khoản 4 Điều 255: v2 xếp hạng `penalty_max_years` và trả lời "Mức cao nhất của Điều 255 là tù chung thân theo khoản 4"; Flat không retrieve nổi bài tin |
| Q5 | cross-kb-multi-hop | 1.00 / 2 | 1.00 / 2 | Hòa (Graph minh bạch hơn) | v2 so ngưỡng bằng số: 9,6kg = 9600g ≥ min_g=100 của khoản 4 Điều 250 trên graph, câu trả lời dẫn thẳng "ngưỡng 100 g trở lên tại điểm b khoản 4" |
| Q6 | aggregation | 0.00 / 1 | 1.00 / 1 | **Graph recall**, judge hòa | Graph liệt kê đủ 3 vụ gold (recall 1.00) nhưng bị judge trừ điểm vì tách vụ Sầm Sơn và vụ Pháp y tâm thần thành 2 ý (thực chất một sự kiện); Flat paraphrase hết tên nên recall 0.00 |

**Quy luật:** với KB 2 nguồn này, GraphRAG **không bao giờ thua** (đúng định lý thiết kế "graph chỉ thêm vào, không thay thế" — cùng top-3 chunk, thêm dữ kiện) và thắng đậm ở mọi câu cần ghép nguồn hoặc tổng hợp (Q3, Q4, Q6: recall 1.00 so với 0.00 của Flat); Flat chỉ đuổi kịp ở câu đáp án nằm gọn một đoạn. Chi phí của sự an toàn đó: mỗi câu đắt hơn 4.9 lần về token.

## 3. Phân tích lỗi (20 điểm)

Các lỗi dưới đây được tôi phát hiện khi chạy ontology gợi ý (bằng chứng "trước": `ket_qua_benchmark_kg.hint.txt` + Cypher trên graph lúc đó), rồi dùng chính chúng làm cơ sở thiết kế ontology v2 — mỗi lỗi ghi kèm kết quả "sau" để chứng minh mức cải thiện.

### Lỗi E2: Thiếu ngữ cảnh luật — câu trả lời sai khung hình phạt dù graph có đủ Điều luật (đã sửa trong v2)

- **Hiện tượng:** trên ontology gợi ý, Q4 (Hoàng Nato, mức tù tối đa) GraphRAG recall=0.00, judge=0.
- **Bằng chứng "trước":** trích `ket_qua_benchmark_kg.hint.txt` (Q4 graph): *"Knowledge graph chỉ nêu **Điều 249 BLHS** về tàng trữ trái phép chất ma túy và **Điều 250 BLHS** về vận chuyển trái phép chất ma túy; không liên hệ Hoàng Nato với hành vi nào, và đoạn trích không nêu mức phạt tù tối đa."* Hai nguyên nhân đã chỉ ra bằng Cypher + tái lập:
  1. **Bộ lọc khoản bỏ sót:** khoản 4 Điều 255 ("tù 20 năm hoặc tù chung thân" — chứa từ khóa `chung thân` của `must_include`) không nhắc chất nào, nên bộ lọc "khoản 1 hoặc khoản MENTIONS chất mà vụ INVOLVES" không bao giờ lấy nó.
  2. **Tràn `max_facts`:** top-3 chunk của Q4 là 3 chunk luật (`blhs-dieu-250/252/249`), `seed_facts` sinh >60 cạnh chỉ-gồm-tên, chiếm sạch `max_facts=60` và cắt mất mọi text khoản.
- **Nguyên nhân:** (1) giả định sai của thiết kế gợi ý — "mọi khung tăng mạnh đều gắn với chất cụ thể" (sai với tội có tình tiết theo hậu quả); (2) thứ tự ghép ngữ cảnh đặt cạnh tên trước text khoản rồi cùng bị cắt.
- **Đề xuất sửa + kết quả "sau":** mô hình hóa khung phạt thành `Clause.penalty_min_years/penalty_max_years` (quy ước chung thân=99, tử hình=100) và khi câu hỏi chứa "tối đa/cao nhất" lấy `top 1 Clause ORDER BY penalty_max_years DESC`; đồng thời đảo thứ tự ngữ cảnh (text khoản trước, cạnh seed sau). Trên v2, cùng truy vấn tái lập với doc_ids luật trả về 60 facts bắt đầu bằng tóm tắt vụ Hoàng Nato + text khoản 1–4 của Điều 249/251/255; benchmark: Q4 recall **0.00 → 1.00**, judge **0 → 2**, câu trả lời: *"Mức cao nhất của Điều 255 là **tù chung thân** theo khoản 4, nhưng chỉ áp dụng khi có các tình tiết hậu quả nghiêm trọng…"*. Đánh đổi: mỗi câu hỏi đắt thêm (in_tok 2925 → 5273) vì giữ nhiều text khoản hơn.

### Lỗi E3: Trùng/lệch thực thể — một thứ ngoài đời thành nhiều node (đã giảm trong v2)

- **Hiện tượng:** trên ontology gợi ý, node `Substance` chứa các tên cùng một chất ngoài đời; một sự kiện thành 2 Case.
- **Bằng chứng "trước" (Cypher trên graph hint):**

```cypher
MATCH (s:Substance) RETURN s.name AS tên ORDER BY toLower(tên);
```

```
17 node, trong đó: 'ma túy', 'ma túy tổng hợp', 'ma túy tổng hợp các loại', 'thuốc lắc',
'Chất ma túy nghi vấn', 'Tinh thể rắn màu trắng nghi là chất ma túy', 'côca' (song song với 'Cocaine')
```

```cypher
MATCH (k:Case) RETURN k.name, k.doc_id;
-- 2 Case 'Phú Quốc ngày 27-9' và 'Phú Quốc ngày 25-9' cùng doc_id news-100260927182621527
```

- **Nguyên nhân:** nằm ở thiết kế khóa định danh: `MERGE` theo chuỗi tên do LLM tự phát minh, hai chuỗi lệch một chữ là hai node; và prompt trích xuất không buộc chất chọn từ danh sách chuẩn (khác với tội danh — nơi ép chuẩn hoạt động tốt: đúng 13 node Crime).
- **Đề xuất sửa + kết quả "sau":** v2 thêm `link_substance` (alias "thuốc lắc"→MDMA, "ma túy đá"/"ma túy tổng hợp"→Methamphetamine, rồi fuzzy cutoff 0.8) và cờ `Substance.canonical`. Sau sửa: 15 Substance; `thuốc lắc`, `ma túy đá` biến mất khỏi danh sách (đã gộp); các tên chưa khớp còn lại **truy vấn được** qua `MATCH (s:Substance {canonical:false})` ('etomidate', 'nước vui', 'ma túy các loại', 'ma túy tổng hợp các loại'…) thay vì trộn lẫn không phân biệt. Còn lại chưa sửa: trùng Case từ cùng một bài — cần khử trùng lặp theo `doc_id` + so summary (đã ghi ONTOLOGY.md mục 8).

### Lỗi E4: Phép đo sai — recall và judge mâu thuẫn (vẫn tồn tại trên v2, đổi chiều)

- **Hiện tượng:** hai phép đo chấm Q6 ngược nhau ở **cả hai ontology**; trên v2: Flat recall=0.00 nhưng judge=1; Graph recall=1.00 nhưng judge=1 (không được 2 dù đáp án đúng đủ).
- **Bằng chứng:** trích `ket_qua_benchmark_kg.txt` (`must_include` = `["Cái Quang Huy", "Lê Minh Thành", "Pháp y tâm thần"]`, gold nêu 3 vụ):
  - Flat: *"Kiện hàng Huy gửi, trong đó có hơn 5,3 kg viên nén được giám định là MDMA… - Vụ Thành mang 5 viên MDMA đi bán. - Vụ khám xét buồng chữa bệnh của Đông…"* — không khớp literal từ khóa nào (recall 0.00) nhưng đúng đủ 3 vụ về ngữ nghĩa.
  - Graph: *"…Vụ vận chuyển hơn 9,6 kg MDMA… (Cái Quang Huy)… - Vụ góp tiền mua ma túy tại Hà Nội: Lê Minh Thành… - Vụ tổ chức sử dụng ma túy tại bãi biển Sầm Sơn… - Vụ sai phạm tại Viện Pháp y tâm thần Trung ương…"* — recall 1.00, nhưng judge chỉ cho 1 vì liệt kê 4 ý trong khi gold là 3 (ý 3 và 4 là cùng một sự kiện, LLM trích xuất đã tạo 2 Case).
- **Nguyên nhân:** thuộc về **phép đo**, không phải pipeline: recall là so chuỗi ký tự cứng (phạt paraphrase đúng); judge là LLM nhìn tổng thể (phạt trùng lặp — mà trùng lặp lại là hệ quả của lỗi E3 phía trích xuất). Ba thành phần (trích xuất, trả lời, chấm) cùng góp vào một điểm số không phản xạsat chất lượng.
- **Đề xuất sửa:** (1) `must_include` kèm biến thể tên ("Thành") hoặc chấm trên entity chuẩn hóa; (2) judge chấm theo checklist từng ý của gold thay vì nhìn tổng thể; (3) gốc rễ: khử trùng lặp Case (đề xuất E3) để answer không tự nhân đôi ý.

*(Ghi nhận thêm E1 — cầu nối gãy có kiểm soát: `MATCH (k:Case) WHERE NOT (k)-[:CHARGED_WITH]->()` trên v2 trả về các case không có tội danh thuộc Chương XX (rửa tiền Sinaloa, "phát hiện nghi vấn" chưa khởi tố) — đây là hành vi đúng của `link_entity` (không nối bừa), không phải lỗi. E6 — `charge`/`sentence` rỗng ở các vai trò "người liên quan"/"nghi phạm" chưa xét xử là hợp lý, nhưng `charge` rỗng cho vai trò "bị cáo" (đã xét xử) là lỗi trích xuất, ví dụ Lê Văn Đông.)*

## 4. Kết luận (5 điểm)

> Với số liệu của mình: Flat RAG đủ cho câu hỏi **single-hop** — Q1, Q2, Q5 hai bên hòa điểm (1.00/2 cả hai), Flat rẻ gấp ~5 lần ($0.00013 so với $0.00064/câu) và nhanh hơn 1.1 giây. Knowledge Graph đáng tiền khi đáp án **rải qua ≥ 2 nguồn**: trên 3 câu cần ghép tin với luật (Q3, Q4, Q6), recall của Graph là **1.00** so với **0.00** của Flat, judge 1.67 so với 0.33; riêng Q3 và Q4 đi từ 0 điểm lên full điểm. Nhưng số này chỉ đạt được sau khi sửa hai lỗi thiết kế (E2/E3): bản ontology gợi ý của chính lab chỉ đạt recall 0.78 — tức **KG "đáng tiền" không phải mặc nhiên, mà phụ thuộc chất lượng ontology và ngữ cảnh đưa vào prompt**. Điều kiện chọn KG: (1) ≥ 1/3 câu hỏi thuộc loại cross-source; (2) entity cầu nối là tập đóng chuẩn hóa được (tội danh: 13 tên — được; chất: phải thêm alias); (3) chấp nhận chi phí một lần ~$0.012 (bằng ~89 câu hỏi Flat) và +$0.00051/câu. Với KB tra cứu thuần văn bản hoặc số câu hỏi nhỏ, Flat RAG vẫn là lựa chọn hợp lý hơn.

## 5. Tự kiểm (5 điểm)

```
$ pytest tests/ -q
................................................                         [100%]
48 passed in 0.14s

$ python bench_kg.py --check
[OK] Dữ liệu: 18 điều luật, 20 bài báo
[OK] KG-1 link_entity
[OK] Neo4j kết nối được
[provider] chat = openrouter:openai/gpt-6-luna | embedding = openrouter:openai/text-embedding-3-small
[OK] KG-2 build_graph: 148 node / 456 cạnh, đường xuyên 2 KB dài 2 cạnh
[OK] KG-3 context: 28 dữ kiện, có Điều 251
[OK] KG-4 GraphRAGAgent.answer
[OK] Chi phí check: 1 lần gọi LLM, $0.00096. ...
```

Ảnh Neo4j: `report/img/kg_count.png`, `report/img/kg_cross_kb.png`, `report/img/kg_my_case.png`.
Người đã chọn cho `kg_my_case.png`: **Cái Quang Huy** — truy vấn
`MATCH p=(:Person {name:'Cái Quang Huy'})-[:INVOLVED_IN]->(k:Case)-[:CHARGED_WITH]->(:Crime)<-[:DEFINES]-(:Article) OPTIONAL MATCH q=(k)-[:INVOLVES|LOCATED_IN]->() RETURN p, q`.

## Vấn đề gặp phải (không tính điểm)

> Không có lỗi nào chặn tiến độ. Ghi chú: (1) session Neo4j Browser tự ngắt vài lần khi thao tác tự động hóa, phải đăng nhập lại — không ảnh hưởng dữ liệu; (2) đơn giá `openai/gpt-6-luna` qua OpenRouter là ước tính theo bảng giá trong `src/llm.py`; (3) sau mỗi lần `bench_kg.py` chạy lại, graph bị dựng mới và tên Case/Person do LLM đặt lệch nhẹ giữa các lần (203 vs 199 nodes) — 3 ảnh trong `report/img/` được chụp trên graph của lần chạy benchmark cuối, khớp với `ket_qua_benchmark_kg.txt`.
