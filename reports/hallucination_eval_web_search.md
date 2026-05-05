# Hallucination Evaluation Report - web_search

Generated: 2026-04-30 12:35 UTC

## Summary

- Source type: web_search
- Question count: 20
- Grounded: 6
- Partially grounded: 7
- Hallucinated: 2
- Correctly refused: 5
- Hallucination rate: 10.0%
- Risky rate: 45.0%

## Question Results

### q01 - available

- Label: grounded
- Question: What machine learning model performed best in the Syracuse water main break study?
- Answer: The model that performed best was the Gradient Boosted Decision Trees (GBDT) algorithm.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The answer correctly states that Gradient Boosted Decision Trees (GBDT) performed best, which is directly supported by multiple evidence excerpts (EVIDENCE 1, 2, and 3) that describe GBDT as the best-performing model. No additional claims are made beyond what the evidence provides.

### q02 - available

- Label: grounded
- Question: How is the prediction problem framed in the Syracuse paper, and why is that framing useful for the city?
- Answer: 

Sources: wm_arxiv_pdf, wm_kdd_page
- Rationale: The answer restates the framing of the problem and its usefulness exactly as described in Evidence 1, with no additional unsupported statements.

### q03 - available

- Label: partially_grounded
- Question: What two operational uses of the risk scores are described for the City of Syracuse?
- Answer: The City of Syracuse uses the risk scores in two ways:  
1. For preventative maintenance on the top 1 % of the riskiest water mains.  
2. To coordinate with the Department of Public Works (DPW) during road construction and maintenance.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The answer correctly identifies the two specific operational uses of risk scores for the City of Syracuse as outlined in Evidence 1: preventative maintenance on the top 1% of riskiest water mains, and coordination with the Department of Public Works (DPW) during road construction and maintenance. However, the answer claims the city 'uses' the risk scores in these ways, while Evidence 1 explicitly states the city 'currently plans to use' these two methods, and no other supplied evidence supports current active implementation of these specific uses. This unsupported claim of present-tense use means not all substantive claims are fully supported.

### q04 - available

- Label: partially_grounded
- Question: What does CRLI stand for, and how is it calculated?
- Answer: CRLI stands for **Combined Real Loss Index**.

It is calculated as the geometric mean of two key IWA (International Water Association) metrics:
- Real losses per connection per day
- Real losses per mains length

The formula is: CRLI = Real losses per connection per day × Real losses per mains length

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer correctly identifies that CRLI stands for Combined Real Loss Index and that it involves the two metrics (real losses per connection per day and real losses per mains length) as stated in the evidence. However, it incorrectly describes the calculation as a simple product rather than the geometric mean (which should be the square root of the product). This misrepresents the calculation method.

### q05 - available

- Label: grounded
- Question: Why is CRLI presented as easier to use than ILI?
- Answer: CRLI is presented as easier to use than ILI for these reasons:
- ILI (Infrastructure Leakage Index) uses several system parameters, is complex to calculate and communicate, and requires expert knowledge for correct application; CRLI combines Op27 and Op28 and is explicitly noted as easier than ILI.
- ILI requires detailed pressure and infrastructure data, a barrier for small and medium-sized utilities, while CRLI assesses real losses without complex pressure data.
- CRLI needs only data utilities already track, is simpler than ILI (despite a strong R² ≈ 0.87 correlation with ILI), and supports benchmarking and performance tracking without extra pressure data.
- CRLI is easier to calculate from available operational data, and requires no pressure data or service connection length.

Sources: crli_news_page, crli_web_pdf
- Rationale: All substantive claims in the answer are directly supported by the evidence. The answer correctly identifies that CRLI is easier to use because: (1) ILI requires detailed pressure and infrastructure data and expert knowledge (Evidence 1), while CRLI works without complex pressure data (Evidence 2); (2) CRLI needs only data utilities already track (Evidence 3); (3) CRLI is explicitly described as easier to calculate from available operational data and requires no pressure data or service connection length (Evidence 4). The answer accurately reflects the comparison between CRLI and ILI presented in the source materials.

### q06 - available

- Label: correctly_refused
- Question: What relationship between CRLI and ILI is reported in the presentation?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf
- Rationale: The question asks for the relationship between CRLI and ILI reported in the presentation. The supplied evidence only mentions ILI as a widely recognized standard real loss metric, and positions CRLI as an alternative, but provides no specific details about the relationship between the two indicators (e.g., correlation strength, R² values). The answer clearly refuses to answer due to insufficient context, which directly aligns with the lack of relevant information in the evidence.

### q07 - missing

- Label: correctly_refused
- Question: What exact hyperparameters were used for the gradient boosted decision tree model?
- Answer: Not enough information in the provided context.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The question asks for the exact hyperparameters of the gradient boosted decision tree model, but none of the provided evidence includes any details about hyperparameter settings. The answer appropriately states that there is not enough information.

### q08 - missing

- Label: correctly_refused
- Question: What annual dollar budget did Syracuse allocate to replace mains in the pilot?
- Answer: Not enough information in the provided context.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The question asks for the annual dollar budget allocated by Syracuse to replace mains in the pilot. None of the provided evidence mentions any budget amount or financial allocation, so the answer appropriately states that the information is not available.

### q09 - missing

- Label: grounded
- Question: What CRLI reference bands have been validated for utilities outside Germany?
- Answer: Not enough information in the provided context.

The evidence only discusses CRLI reference bands validated for German utilities (105 utilities in Rhineland-Palatinate and Saarland, Germany). The "possible preliminary CRLI reference bands" mentioned (Low < 10 | MODERATE 10–20 | High > 20) are based on German data, and the evidence explicitly states this is still "ahead" in terms of defining reference bands. There is no information in the provided context about validation or application of CRLI reference bands for utilities outside Germany.

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer correctly states that the provided evidence only covers German utilities and does not contain information about validation of CRLI reference bands for utilities outside Germany. This claim is directly supported by the evidence, which mentions only German data and notes that defining reference bands is still pending.

### q10 - missing

- Label: correctly_refused
- Question: Which French utility first adopted CRLI after the conference?
- Answer: Not enough information in the provided context.

The evidence discusses the presentation of CRLI at the PI2025 conference in Poznań and mentions real-world applications in several countries, but it does not identify any French utility or specify which utility first adopted CRLI after the conference. The specific utilities mentioned in the evidence are from Germany (Rhineland-Palatinate and Saarland).

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer states that the provided evidence does not identify a French utility that first adopted CRLI, which is accurate because none of the evidence mentions any French utility; only German utilities are referenced. The response correctly refuses to answer due to insufficient information.

### q11 - missing

- Label: correctly_refused
- Question: What pressure-corrected formula replaced CRLI in the final policy recommendation?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf
- Rationale: The question asks for the pressure-corrected formula that replaced CRLI in the final policy recommendation. The provided evidence exclusively describes the CRLI metric, including its definition, calculation method, benefits, and use cases, with no mention of any replacement formula for CRLI, any pressure-corrected alternative, or any final policy recommendation related to replacing CRLI. The graded answer clearly refuses to answer the question due to insufficient evidence, which is fully consistent with the available evidence.

### q12 - conflicting

- Label: grounded
- Question: How many breaks occurred on the riskiest 52 mains during the Syracuse pilot?
- Answer: The sources conflict:  
- source wm_arxiv_abs reports 33 breaks on the riskiest 52 mains.  
- source wm_kdd_page reports 42 breaks on the riskiest 52 mains.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The answer accurately reflects the conflicting information present in the supplied evidence. It cites the 33‑break figure from source wm_arxiv_abs (and corroborated by wm_arxiv_pdf) and the 42‑break figure from source wm_kdd_page, matching the statements in the evidence. No additional claims are made beyond what the evidence supports.

### q13 - conflicting

- Label: partially_grounded
- Question: What mean CRLI value is reported for Rhineland-Palatinate?
- Answer: The mean CRLI value reported for Rhineland-Palatinate is approximately 7.16.

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer correctly identifies the mean CRLI value for Rhineland-Palatinate as 7.16 based on evidence from crli_web_pdf (EVIDENCE 3 and EVIDENCE 4). However, it does not acknowledge the conflicting information presented in crli_news_page (EVIDENCE 1), which reports a different mean of 6.14 for Rhineland-Palatinate.

### q14 - conflicting

- Label: hallucinated
- Question: What mean CRLI value is reported for Saarland?
- Answer: The mean CRLI value reported for Saarland is approximately 7.79.

Sources: crli_news_page, crli_web_pdf
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

### q15 - conflicting

- Label: hallucinated
- Question: Is the Syracuse system described only as a pilot, or as already deployed in the city?
- Answer: The Syracuse system is described as both a pilot and already deployed in the city.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

### q16 - mixed

- Label: grounded
- Question: Which city deployed the water-main prediction model, and which two German regions are used in the CRLI evidence base?
- Answer: The water-main prediction model was deployed in Syracuse, N.Y. The two German regions used in the CRLI evidence base are not mentioned in the provided evidence.

Sources: wm_arxiv_abs, wm_arxiv_pdf
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

### q17 - mixed

- Label: partially_grounded
- Question: Compare the simplification strategy in both documents: what existing practice or metric is each document trying to improve on?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf, wm_arxiv_pdf
- Rationale: The answer refused even though some evidence was available.

### q18 - mixed

- Label: partially_grounded
- Question: Which document uses temporal cross-validation, and which one reports an R^2 of about 0.87?
- Answer: Not enough information in the provided context.

Sources: wm_arxiv_abs, wm_arxiv_pdf
- Rationale: The answer refused even though some evidence was available.

### q19 - mixed

- Label: partially_grounded
- Question: How do the two documents encode structural context when evaluating infrastructure risk or loss?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf, wm_arxiv_pdf
- Rationale: The answer refused even though some evidence was available.

### q20 - mixed

- Label: partially_grounded
- Question: Across both documents, what practical decision-making benefit is emphasized for utilities or city operations?
- Answer: 

Sources: crli_web_pdf, wm_arxiv_abs
- Rationale: The model returned no substantive answer body even though the prompt expected one.
