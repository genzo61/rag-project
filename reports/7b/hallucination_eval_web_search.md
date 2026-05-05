# Hallucination Evaluation Report - web_search

Generated: 2026-05-04 19:00 UTC

## Summary

- Source type: web_search
- Model used for answer generation: qwen2.5:7b
- Run slug: 7b
- Question count: 20
- Grounded: 5
- Partially grounded: 7
- Hallucinated: 3
- Correctly refused: 5
- Hallucination rate: 15.0%
- Risky rate: 50.0%

## Question Results

### q01 - available

- Label: grounded
- Question: What machine learning model performed best in the Syracuse water main break study?
- Answer: The gradient boosted decision trees performed best, achieving precision at 1% ([email protected]) of 0.62.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

### q02 - available

- Label: grounded
- Question: How is the prediction problem framed in the Syracuse paper, and why is that framing useful for the city?
- Answer: The prediction problem is framed as a binary classification problem to determine whether a water main break will occur on a given city block within the next three years. This framing allows the city of Syracuse to easily operationalize the model and plan infrastructure development for the next three years.

Sources: wm_arxiv_pdf, wm_kdd_page
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

### q03 - available

- Label: grounded
- Question: What two operational uses of the risk scores are described for the City of Syracuse?
- Answer: The two operational uses of the risk scores for the City of Syracuse are:
1) For preventative maintenance on the top 1% of the riskiest water mains.
2) To use the risk scores to coordinate with the Department of Public Works (DPW) during road construction and maintenance.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

### q04 - available

- Label: grounded
- Question: What does CRLI stand for, and how is it calculated?
- Answer: CRLI stands for Combined Real Loss Index.

The CRLI is calculated as the Geometric Mean of two key IWA metrics: Real losses per connection per day and Real losses per mains length.

Sources: crli_news_page, crli_web_pdf
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

### q05 - available

- Label: grounded
- Question: Why is CRLI presented as easier to use than ILI?
- Answer: CRLI is presented as easier to use than ILI because it combines Op27 and Op28 in a way that is more balanced for varying network structures, making it suitable for both urban and rural systems with different connection densities. Additionally, CRLI requires less data input since it only needs data utilities already track, whereas ILI might need pressure data or service connection length which are not always readily available.

Sources: crli_news_page, crli_web_pdf
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

### q06 - available

- Label: partially_grounded
- Question: What relationship between CRLI and ILI is reported in the presentation?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer refused even though some evidence was available.

### q07 - missing

- Label: correctly_refused
- Question: What exact hyperparameters were used for the gradient boosted decision tree model?
- Answer: Not enough information in the provided context.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The answer refused and the question belongs to the missing-information class.

### q08 - missing

- Label: correctly_refused
- Question: What annual dollar budget did Syracuse allocate to replace mains in the pilot?
- Answer: Not enough information in the provided context.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The answer refused and the question belongs to the missing-information class.

### q09 - missing

- Label: correctly_refused
- Question: What CRLI reference bands have been validated for utilities outside Germany?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer refused and the question belongs to the missing-information class.

### q10 - missing

- Label: correctly_refused
- Question: Which French utility first adopted CRLI after the conference?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer refused and the question belongs to the missing-information class.

### q11 - missing

- Label: correctly_refused
- Question: What pressure-corrected formula replaced CRLI in the final policy recommendation?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer refused and the question belongs to the missing-information class.

### q12 - conflicting

- Label: partially_grounded
- Question: How many breaks occurred on the riskiest 52 mains during the Syracuse pilot?
- Answer: Not enough information in the provided context.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The answer refused even though some evidence was available.

### q13 - conflicting

- Label: hallucinated
- Question: What mean CRLI value is reported for Rhineland-Palatinate?
- Answer: The mean CRLI value reported for Rhineland-Palatinate is approximately 6.14.

Sources: crli_news_page, crli_web_pdf
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

### q14 - conflicting

- Label: hallucinated
- Question: What mean CRLI value is reported for Saarland?
- Answer: The mean CRLI value reported for Saarland is approximately 7.79.

Sources: crli_news_page, crli_web_pdf
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

### q15 - conflicting

- Label: hallucinated
- Question: Is the Syracuse system described only as a pilot, or as already deployed in the city?
- Answer: The Syracuse system is described as both deployed and in a pilot phase. It is currently deployed in the City of Syracuse, but it is also being conducted as a field trial to calculate the risk of failure for each city block over the period 2016-2018 using data up to the end of 2015.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

### q16 - mixed

- Label: partially_grounded
- Question: Which city deployed the water-main prediction model, and which two German regions are used in the CRLI evidence base?
- Answer: Syracuse, N.Y. deployed the water-main prediction model.

Sources: wm_arxiv_abs, wm_arxiv_pdf
- Rationale: Fallback lexical check found partial overlap with the reference answer.

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
- Answer: Not enough information in the provided context.

Sources: crli_web_pdf, wm_arxiv_abs
- Rationale: The answer refused even though some evidence was available.
