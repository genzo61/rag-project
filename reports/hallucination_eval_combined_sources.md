# Hallucination Evaluation Report - combined_sources

Generated: 2026-04-30 12:35 UTC

## Summary

- Source type: combined_sources
- Question count: 20
- Grounded: 9
- Partially grounded: 7
- Hallucinated: 1
- Correctly refused: 3
- Hallucination rate: 5.0%
- Risky rate: 40.0%

## Question Results

### q01 - available

- Label: grounded
- Question: What machine learning model performed best in the Syracuse water main break study?
- Answer: The study found that the Gradient Boosting Decision Trees (GBDT) model performed best.

Sources: eval_water_main_breaks, wm_01, wm_05, wm_arxiv_abs, wm_arxiv_pdf
- Rationale: The answer correctly states that Gradient Boosting Decision Trees performed best, which is directly supported by multiple evidence excerpts (EVIDENCE 2, 5, 6). No additional claims are made beyond what the evidence provides.

### q02 - available

- Label: grounded
- Question: How is the prediction problem framed in the Syracuse paper, and why is that framing useful for the city?
- Answer: The Syracuse paper frames the prediction problem as a binary classification task: “whether a water main break will occur on a given city block within the next three years.” This framing allows the city to operationalize the model and plan infrastructure development over the next three years.

Sources: eval_water_main_breaks, wm_06, wm_07, wm_kdd_page
- Rationale: Every substantive claim in the answer is directly supported by the provided evidence. The framing of the prediction problem as a binary classification task (predicting whether a water main break will occur on a given city block within the next three years) is explicitly confirmed in Evidence 1, 3, and 5. The stated utility of this framing—enabling the city of Syracuse to operationalize the model and plan infrastructure development over a three-year horizon—is explicitly stated in Evidence 1 and 4. There are no unsupported, incomplete, or overconfident claims, and no conflicting evidence that the answer fails to acknowledge.

### q03 - available

- Label: grounded
- Question: What two operational uses of the risk scores are described for the City of Syracuse?
- Answer: The two operational uses of the risk scores for the City of Syracuse are:

1. **Preventative maintenance** on the top 1% of the riskiest water mains
2. **Coordination with the Department of Public Works (DPW)** during road construction and maintenance

Sources: eval_water_main_breaks, wm_10, wm_13, wm_arxiv_pdf
- Rationale: All substantive claims in the answer (the two operational uses of the risk scores for the City of Syracuse) are explicitly and directly supported by the provided evidence. Evidence 1 and Evidence 5 both enumerate the exact two uses: 1) preventative maintenance on the top 1% of the riskiest water mains, and 2) coordination with the Department of Public Works (DPW) during road construction and maintenance. Evidence 3 additionally confirms the second use. Evidence 2 and Evidence 4 note the system is deployed and risk scores are in use, supporting the characterization of these as operational uses. There are no unsupported, incomplete, or overconfident claims, and no conflicting evidence requiring acknowledgment.

### q04 - available

- Label: partially_grounded
- Question: What does CRLI stand for, and how is it calculated?
- Answer: CRLI stands for Combined Real Loss Index. It is the Geometric Mean of two key IWA metrics: real losses per connection per day, and real losses per mains length. The provided calculation formula is CRLI = (Real losses per connection per day) × (Real losses per mains length). It can be calculated from operational data utilities already track and does not require pressure data or service connection length.

Sources: crli_04, crli_08, crli_news_page, crli_web_pdf, eval_crli
- Rationale: The answer correctly states the meaning of CRLI and that it is based on the geometric mean of two metrics, which is supported by the evidence. It also correctly notes that it can be calculated from operational data without pressure or service connection length, also supported. However, the answer gives an incorrect formula (simple multiplication) for the geometric mean, which is not supported by the evidence and misrepresents the calculation.

### q05 - available

- Label: grounded
- Question: Why is CRLI presented as easier to use than ILI?
- Answer: CRLI is presented as easier to use than ILI because ILI (Infrastructure Leakage Index) is complex to calculate and communicate, requires expert knowledge for correct application, and often requires detailed pressure and infrastructure data, a barrier for small and medium-sized utilities. CRLI does not require complex pressure or general complex data, is a practical and accessible alternative to ILI, combines Op27 and Op28 to be better balanced for varying network structures, and enables fair consistent benchmarking across diverse utilities without complex data needs.

Sources: crli_03, crli_06, crli_news_page, eval_crli
- Rationale: Every substantive claim in the answer is directly supported by the provided evidence, with no unsupported, incomplete, or overconfident claims, and no conflicting evidence that requires acknowledgment. Evidence 1 confirms ILI (Op29) is complex to calculate and communicate, requires expert knowledge, and that CRLI combines Op27 and Op28, is easier than ILI, and better balanced for varying network structures. Evidence 2 confirms CRLI is a practical and accessible alternative to ILI, enables fair and consistent benchmarking across diverse utilities without requiring complex data. Evidence 3 corroborates that CRLI is easier than ILI and better balanced across different network structures. Evidence 5 confirms ILI often requires detailed pressure and infrastructure data (a barrier for small and medium-sized utilities) and that CRLI does not require complex pressure data. The answer's inclusion of crli_06 in its source list is not reflected in the answer content, but this is an attribution discrepancy, not an unsupported substantive claim.

### q06 - available

- Label: grounded
- Question: What relationship between CRLI and ILI is reported in the presentation?
- Answer: The presentation reports that CRLI is strongly related to ILI, with a fitted linear model (CRLI = 12.907 × ILI) that explains about 87 % of the variation (R² ≈ 0.87).

Sources: crli_06, crli_07, crli_news_page, eval_crli
- Rationale: The answer accurately reflects the evidence provided. Evidence 1 explicitly states a strong relationship with R² = 0.87 and gives the model CRLI = 12.907 × ILI. Evidence 3 also confirms a strong relationship with R² around 0.87. No conflicting evidence is present. All claims in the answer are directly supported by the cited sources.

### q07 - missing

- Label: grounded
- Question: What exact hyperparameters were used for the gradient boosted decision tree model?
- Answer: The gradient‑boosted decision‑tree model was trained with:

* **Boosting iterations:** 100  
* **Maximum tree depth:** 3 (limiting the number of terminal nodes)  
* **Subsampling rate:** 50 % of the training samples for each base learner (stochastic gradient boosting)

Sources: eval_water_main_breaks, wm_01, wm_04, wm_arxiv_abs, wm_arxiv_pdf
- Rationale: All substantive claims in the answer are directly supported by the provided evidence. Evidence 2 explicitly states the boosting iterations (100), maximum tree depth (3), and subsampling rate (50%). No unsupported or contradictory statements are present.

### q08 - missing

- Label: correctly_refused
- Question: What annual dollar budget did Syracuse allocate to replace mains in the pilot?
- Answer: Not enough information in the provided context.

Sources: eval_water_main_breaks, wm_01, wm_13, wm_arxiv_abs
- Rationale: The question asks for the specific annual dollar budget Syracuse allocated to replace mains in its pilot program. The graded answer clearly refuses to provide this information, stating there is not enough information in the provided context. All reviewed evidence discusses the pilot's ML risk assessment system, water main break statistics, coordination between city departments, and pilot timeline, but none include any specific budget figures for main replacement in the pilot. This refusal is fully justified by the insufficient evidence, aligning with the correctly_refused label criteria.

### q09 - missing

- Label: grounded
- Question: What CRLI reference bands have been validated for utilities outside Germany?
- Answer: Not enough information in the provided context.

Sources: crli_01, crli_12, crli_news_page, crli_web_pdf, eval_crli
- Rationale: The answer correctly states that there is no evidence of validated CRLI reference bands for utilities outside Germany, which aligns with the supplied evidence that the bands are only indicative and may need local validation. No unsupported claims are made.

### q10 - missing

- Label: correctly_refused
- Question: Which French utility first adopted CRLI after the conference?
- Answer: Not enough information in the provided context.

Sources: crli_02, crli_03, crli_news_page, crli_web_pdf, eval_crli
- Rationale: The question asks to identify the first French utility to adopt CRLI after the 10th IWA conference. All provided evidence covers CRLI's definition, statistical robustness, and application in German utility regions (Rhineland-Palatinate, Saarland), but contains no mention of French utilities adopting CRLI, nor any information about which entity first adopted CRLI post-conference. The answer correctly refuses to provide a substantive response due to insufficient evidence, which aligns exactly with the content of the provided evidence.

### q11 - missing

- Label: correctly_refused
- Question: What pressure-corrected formula replaced CRLI in the final policy recommendation?
- Answer: Not enough informationin the provided context.

Sources: crli_02, crli_03, crli_news_page, crli_web_pdf, eval_crli
- Rationale: The question asks for a specific pressure-corrected formula that replaced CRLI, but none of the provided evidence mentions any replacement formula. The answer appropriately states that there is not enough information, which aligns with the lack of supporting evidence.

### q12 - conflicting

- Label: grounded
- Question: How many breaks occurred on the riskiest 52 mains during the Syracuse pilot?
- Answer: The evidence contains conflicting claims about the number of breaks on the riskiest 52 mains during the Syracuse pilot.  
- Claims 33 breaks: EVIDENCE 1, EVIDENCE 4, EVIDENCE 5  
- Claims 42 breaks: EVIDENCE 3, EVIDENCE 6  

Sources conflict.

Sources: eval_water_main_breaks, wm_11, wm_12, wm_arxiv_abs, wm_kdd_page
- Rationale: The answer accurately reflects the evidence, noting that some sources report 33 breaks and others report 42 breaks, and correctly identifies the specific evidence pieces supporting each claim without making unsupported assertions.

### q13 - conflicting

- Label: partially_grounded
- Question: What mean CRLI value is reported for Rhineland-Palatinate?
- Answer: 

Sources: crli_08, crli_09, crli_news_page, eval_crli
- Rationale: The model returned no substantive answer body even though the prompt expected one.

### q14 - conflicting

- Label: partially_grounded
- Question: What mean CRLI value is reported for Saarland?
- Answer: 

Sources: crli_10, crli_11, crli_news_page, eval_crli
- Rationale: The model returned no substantive answer body even though the prompt expected one.

### q15 - conflicting

- Label: hallucinated
- Question: Is the Syracuse system described only as a pilot, or as already deployed in the city?
- Answer: The system is described as both deployed in the City of Syracuse and being field-validated through a pilot or trial.

Sources: eval_water_main_breaks, wm_09, wm_13, wm_arxiv_abs, wm_kdd_page
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

### q16 - mixed

- Label: grounded
- Question: Which city deployed the water-main prediction model, and which two German regions are used in the CRLI evidence base?
- Answer: The city that deployed the water-main prediction model is Syracuse.
The two German regions used in the CRLI evidence base are Rhineland-Palatinate and Saarland.

Sources: eval_crli, eval_water_main_breaks, wm_03, wm_05, wm_arxiv_abs
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

### q17 - mixed

- Label: partially_grounded
- Question: Compare the simplification strategy in both documents: what existing practice or metric is each document trying to improve on?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf, eval_crli, eval_water_main_breaks, wm_01, wm_02
- Rationale: The answer refused even though some evidence was available.

### q18 - mixed

- Label: partially_grounded
- Question: Which document uses temporal cross-validation, and which one reports an R^2 of about 0.87?
- Answer: Not enough information in the provided context.

Sources: crli_08, eval_water_main_breaks, wm_08, wm_arxiv_pdf
- Rationale: The answer refused even though some evidence was available.

### q19 - mixed

- Label: partially_grounded
- Question: How do the two documents encode structural context when evaluating infrastructure risk or loss?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, eval_crli, wm_02, wm_07
- Rationale: The answer refused even though some evidence was available.

### q20 - mixed

- Label: partially_grounded
- Question: Across both documents, what practical decision-making benefit is emphasized for utilities or city operations?
- Answer: 

Sources: crli_web_pdf, eval_crli, eval_water_main_breaks, wm_02, wm_09
- Rationale: The model returned no substantive answer body even though the prompt expected one.
