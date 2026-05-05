# Hallucination Evaluation Report

Generated: 2026-05-04 19:00 UTC

## Scope

- Model used for answer generation: qwen2.5:7b
- Run slug: 7b
- Question count: 20
- Source types evaluated: Vector DB, DP DB, web search, combined sources
- Labels: grounded, partially_grounded, hallucinated, correctly_refused

## Hallucination Rate By Source Type

| Source type | Total | Grounded | Partial | Hallucinated | Correctly refused | Hallucination rate | Risky rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| vector_db | 20 | 3 | 10 | 2 | 5 | 10.0% | 60.0% |
| dp_db | 20 | 3 | 9 | 3 | 5 | 15.0% | 60.0% |
| web_search | 20 | 5 | 7 | 3 | 5 | 15.0% | 50.0% |
| combined_sources | 20 | 4 | 10 | 1 | 5 | 5.0% | 55.0% |

## Good Examples

### q01 - web_search

- Category: available
- Label: grounded
- Question: What machine learning model performed best in the Syracuse water main break study?
- Answer: The gradient boosted decision trees performed best, achieving precision at 1% ([email protected]) of 0.62.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Why it is good: Fallback lexical check found substantial overlap with the reference answer.

### q02 - vector_db

- Category: available
- Label: grounded
- Question: How is the prediction problem framed in the Syracuse paper, and why is that framing useful for the city?
- Answer: The prediction problem is framed as a binary classification problem to determine whether a water main break will occur on a given city block within the next three years. This framing allows the city of Syracuse to easily operationalize the model and plan infrastructure development for the next three years.

Sources: eval_water_main_breaks
- Why it is good: Fallback lexical check found substantial overlap with the reference answer.

### q02 - dp_db

- Category: available
- Label: grounded
- Question: How is the prediction problem framed in the Syracuse paper, and why is that framing useful for the city?
- Answer: The prediction problem is framed as a binary classification problem: whether a water main break will occur on a given city block within the next three years. This framing helps Syracuse operationalize the model and plan infrastructure development over the next three years.

Sources: wm_06, wm_07, wm_08, wm_13
- Why it is good: Fallback lexical check found substantial overlap with the reference answer.

### q02 - web_search

- Category: available
- Label: grounded
- Question: How is the prediction problem framed in the Syracuse paper, and why is that framing useful for the city?
- Answer: The prediction problem is framed as a binary classification problem to determine whether a water main break will occur on a given city block within the next three years. This framing allows the city of Syracuse to easily operationalize the model and plan infrastructure development for the next three years.

Sources: wm_arxiv_pdf, wm_kdd_page
- Why it is good: Fallback lexical check found substantial overlap with the reference answer.

## Bad Examples

### q01 - vector_db

- Category: available
- Label: partially_grounded
- Question: What machine learning model performed best in the Syracuse water main break study?
- Answer: The machine learning model that performed best was the Syracuse Model (GBDT) with a precision at 1% of 0.62.

Sources: eval_water_main_breaks
- Why it is bad: Fallback lexical check found partial overlap with the reference answer.

### q01 - dp_db

- Category: available
- Label: partially_grounded
- Question: What machine learning model performed best in the Syracuse water main break study?
- Answer: Not enough information in the provided context.

Sources: wm_01, wm_03, wm_05, wm_06
- Why it is bad: The answer refused even though some evidence was available.

### q01 - combined_sources

- Category: available
- Label: partially_grounded
- Question: What machine learning model performed best in the Syracuse water main break study?
- Answer: Not enough information in the provided context.

Sources: eval_water_main_breaks, wm_01, wm_05, wm_arxiv_abs, wm_arxiv_pdf
- Why it is bad: The answer refused even though some evidence was available.

### q03 - dp_db

- Category: available
- Label: partially_grounded
- Question: What two operational uses of the risk scores are described for the City of Syracuse?
- Answer: Not enough information in the provided context.

Sources: wm_02, wm_09, wm_10, wm_13
- Why it is bad: The answer refused even though some evidence was available.

## Common Hallucination Patterns

- Conflicting-source questions produced 16 weak answers, which suggests the assistant often collapses contradictory evidence into one claim.
- Mixed-source questions produced 19 weak answers, indicating that multi-hop synthesis is a common failure point.
- Even answerable questions produced 10 weak answers, which points to unsupported elaboration beyond the retrieved evidence.

## Grounding Recommendations

- Refuse by default when no retrieved chunk directly answers the question, instead of asking the LLM to infer from nearby context.
- When two sources disagree on a numeric value or status, route the answer through a conflict template that lists each claim with attribution.
- Require the orchestrator to verify that every sentence in a draft answer is traceable to at least one retrieved chunk before returning it.
- Prefer source-specific answering first, then synthesize across sources only if the question explicitly needs multiple sources.
- Add a retrieval sufficiency check: if the top chunks do not cover all named entities or sub-questions, return an insufficiency refusal.
- For mixed-source questions, force the prompt to answer in source-attributed clauses so the model cannot silently merge unrelated evidence.
- Down-rank summary slides or promotional pages when detailed primary evidence is available, because they are more likely to compress or distort exact statistics.
- Treat unsupported numbers, dates, and proper nouns as high-risk claims and require explicit citation-ready evidence before including them.

## Detailed Results By Source Type

Each section below shows the evaluated questions, the model answer, and the final label for one source type.

### vector_db

#### q01 - available

- Label: partially_grounded
- Question: What machine learning model performed best in the Syracuse water main break study?
- Answer: The machine learning model that performed best was the Syracuse Model (GBDT) with a precision at 1% of 0.62.

Sources: eval_water_main_breaks
- Rationale: Fallback lexical check found partial overlap with the reference answer.

#### q02 - available

- Label: grounded
- Question: How is the prediction problem framed in the Syracuse paper, and why is that framing useful for the city?
- Answer: The prediction problem is framed as a binary classification problem to determine whether a water main break will occur on a given city block within the next three years. This framing allows the city of Syracuse to easily operationalize the model and plan infrastructure development for the next three years.

Sources: eval_water_main_breaks
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q03 - available

- Label: grounded
- Question: What two operational uses of the risk scores are described for the City of Syracuse?
- Answer: The two operational uses of the risk scores for the City of Syracuse are:
1) For preventative maintenance on the top 1% of the riskiest water mains.
2) To use the risk scores to coordinate with the Department of Public Works (DPW) as they do road construction and maintenance.

Sources: eval_water_main_breaks
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q04 - available

- Label: grounded
- Question: What does CRLI stand for, and how is it calculated?
- Answer: CRLI stands for Combined Real Loss Index. It is calculated as the geometric mean of real losses per connection per day and real losses per mains length.

Sources: eval_crli
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q05 - available

- Label: partially_grounded
- Question: Why is CRLI presented as easier to use than ILI?
- Answer: CRLI is presented as easier to use than ILI because it combines Op27 and Op28 in a more balanced way for different network structures, promotes better understanding among asset-management teams, and positions itself as a practical alternative that requires data utilities already track, making it simpler and more accessible. Additionally, CRLI has a strong correlation with ILI, which further supports its ease of use.

Sources: eval_crli
- Rationale: Fallback lexical check found partial overlap with the reference answer.

#### q06 - available

- Label: partially_grounded
- Question: What relationship between CRLI and ILI is reported in the presentation?
- Answer: CRLI Responds Strongly to ILI – Confirmed by Model Fit with R2 = 0.87, CRLI = 12.907 × ILI^0.9428.

Sources: eval_crli
- Rationale: Fallback lexical check found partial overlap with the reference answer.

#### q07 - missing

- Label: correctly_refused
- Question: What exact hyperparameters were used for the gradient boosted decision tree model?
- Answer: Not enough information in the provided context.

Sources: eval_water_main_breaks
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q08 - missing

- Label: correctly_refused
- Question: What annual dollar budget did Syracuse allocate to replace mains in the pilot?
- Answer: Not enough information in the provided context.

Sources: eval_water_main_breaks
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q09 - missing

- Label: correctly_refused
- Question: What CRLI reference bands have been validated for utilities outside Germany?
- Answer: Not enough information in the provided context.

Sources: eval_crli
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q10 - missing

- Label: correctly_refused
- Question: Which French utility first adopted CRLI after the conference?
- Answer: Not enough information in the provided context.

Sources: eval_crli
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q11 - missing

- Label: correctly_refused
- Question: What pressure-corrected formula replaced CRLI in the final policy recommendation?
- Answer: Not enough information in the provided context.

Sources: eval_crli
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q12 - conflicting

- Label: partially_grounded
- Question: How many breaks occurred on the riskiest 52 mains during the Syracuse pilot?
- Answer: Not enough information in the provided context.

Sources: eval_water_main_breaks
- Rationale: The answer refused even though some evidence was available.

#### q13 - conflicting

- Label: hallucinated
- Question: What mean CRLI value is reported for Rhineland-Palatinate?
- Answer: The mean CRLI value reported for Rhineland-Palatinate is approximately 6.14.

Sources: eval_crli
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

#### q14 - conflicting

- Label: partially_grounded
- Question: What mean CRLI value is reported for Saarland?
- Answer: Not enough information in the provided context.

Sources: eval_crli
- Rationale: The answer refused even though some evidence was available.

#### q15 - conflicting

- Label: hallucinated
- Question: Is the Syracuse system described only as a pilot, or as already deployed in the city?
- Answer: The Syracuse system is described as both deployed and in a field trial, indicating it has already been implemented but is still being validated.

Sources: eval_water_main_breaks
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

#### q16 - mixed

- Label: partially_grounded
- Question: Which city deployed the water-main prediction model, and which two German regions are used in the CRLI evidence base?
- Answer: The city that deployed the water-main prediction model is Syracuse.

Sources: eval_crli, eval_water_main_breaks
- Rationale: Fallback lexical check found partial overlap with the reference answer.

#### q17 - mixed

- Label: partially_grounded
- Question: Compare the simplification strategy in both documents: what existing practice or metric is each document trying to improve on?
- Answer: Not enough information in the provided context.

Sources: eval_crli, eval_water_main_breaks
- Rationale: The answer refused even though some evidence was available.

#### q18 - mixed

- Label: partially_grounded
- Question: Which document uses temporal cross-validation, and which one reports an R^2 of about 0.87?
- Answer: Not enough information in the provided context.

Sources: eval_water_main_breaks
- Rationale: The answer refused even though some evidence was available.

#### q19 - mixed

- Label: partially_grounded
- Question: How do the two documents encode structural context when evaluating infrastructure risk or loss?
- Answer: Not enough information in the provided context.

Sources: eval_crli, eval_water_main_breaks
- Rationale: The answer refused even though some evidence was available.

#### q20 - mixed

- Label: partially_grounded
- Question: Across both documents, what practical decision-making benefit is emphasized for utilities or city operations?
- Answer: The practical decision-making benefit emphasized for utilities or city operations is the ability to enable more robust data collection and better-informed decisions through the use of CRLI as a metric.

Sources: eval_crli, eval_water_main_breaks
- Rationale: Fallback lexical check found partial overlap with the reference answer.

### dp_db

#### q01 - available

- Label: partially_grounded
- Question: What machine learning model performed best in the Syracuse water main break study?
- Answer: Not enough information in the provided context.

Sources: wm_01, wm_03, wm_05, wm_06
- Rationale: The answer refused even though some evidence was available.

#### q02 - available

- Label: grounded
- Question: How is the prediction problem framed in the Syracuse paper, and why is that framing useful for the city?
- Answer: The prediction problem is framed as a binary classification problem: whether a water main break will occur on a given city block within the next three years. This framing helps Syracuse operationalize the model and plan infrastructure development over the next three years.

Sources: wm_06, wm_07, wm_08, wm_13
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q03 - available

- Label: partially_grounded
- Question: What two operational uses of the risk scores are described for the City of Syracuse?
- Answer: Not enough information in the provided context.

Sources: wm_02, wm_09, wm_10, wm_13
- Rationale: The answer refused even though some evidence was available.

#### q04 - available

- Label: grounded
- Question: What does CRLI stand for, and how is it calculated?
- Answer: CRLI stands for Combined Real Loss Index. It does not require pressure data or service connection length and can be calculated from operational data utilities already track.

Sources: crli_01, crli_04, crli_08, crli_10
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q05 - available

- Label: hallucinated
- Question: Why is CRLI presented as easier to use than ILI?
- Answer: CRLI is presented as easier to use than ILI while maintaining a strong relationship with it, as indicated by an R-squared value around 0.87 in a fitted model.

Sources: crli_01, crli_02, crli_03, crli_06
- Rationale: Fallback lexical check found weak overlap with the expected grounded answer.

#### q06 - available

- Label: grounded
- Question: What relationship between CRLI and ILI is reported in the presentation?
- Answer: The presentation reports that CRLI has a strong relationship with ILI, with a fitted model showing R-squared around 0.87.

Sources: crli_02, crli_06, crli_07, crli_12
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q07 - missing

- Label: correctly_refused
- Question: What exact hyperparameters were used for the gradient boosted decision tree model?
- Answer: Not enough information in the provided context.

Sources: wm_01, wm_03, wm_04, wm_05
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q08 - missing

- Label: correctly_refused
- Question: What annual dollar budget did Syracuse allocate to replace mains in the pilot?
- Answer: Not enough information in the provided context.

Sources: wm_01, wm_07, wm_09, wm_13
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q09 - missing

- Label: correctly_refused
- Question: What CRLI reference bands have been validated for utilities outside Germany?
- Answer: Not enough information in the provided context.

Sources: crli_01, crli_04, crli_05, crli_12
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q10 - missing

- Label: correctly_refused
- Question: Which French utility first adopted CRLI after the conference?
- Answer: Not enough information in the provided context.

Sources: crli_02, crli_03, crli_06, crli_07
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q11 - missing

- Label: correctly_refused
- Question: What pressure-corrected formula replaced CRLI in the final policy recommendation?
- Answer: Not enough information in the provided context.

Sources: crli_02, crli_03, crli_04, crli_06
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q12 - conflicting

- Label: partially_grounded
- Question: How many breaks occurred on the riskiest 52 mains during the Syracuse pilot?
- Answer: Not enough information in the provided context.

Sources: wm_09, wm_11, wm_12, wm_13
- Rationale: The answer refused even though some evidence was available.

#### q13 - conflicting

- Label: partially_grounded
- Question: What mean CRLI value is reported for Rhineland-Palatinate?
- Answer: Not enough information in the provided context.

Sources: crli_05, crli_08, crli_09, crli_10
- Rationale: The answer refused even though some evidence was available.

#### q14 - conflicting

- Label: partially_grounded
- Question: What mean CRLI value is reported for Saarland?
- Answer: Not enough information in the provided context.

Sources: crli_08, crli_09, crli_10, crli_11
- Rationale: The answer refused even though some evidence was available.

#### q15 - conflicting

- Label: hallucinated
- Question: Is the Syracuse system described only as a pilot, or as already deployed in the city?
- Answer: The Syracuse system is described as both deployed in the City of Syracuse and having been field-validated through a pilot or trial.

Sources: wm_01, wm_02, wm_09, wm_13
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

#### q16 - mixed

- Label: partially_grounded
- Question: Which city deployed the water-main prediction model, and which two German regions are used in the CRLI evidence base?
- Answer: Not enough information in the provided context.

Sources: wm_03, wm_05, wm_06, wm_08
- Rationale: The answer refused even though some evidence was available.

#### q17 - mixed

- Label: hallucinated
- Question: Compare the simplification strategy in both documents: what existing practice or metric is each document trying to improve on?
- Answer: The first document is trying to improve on existing reactive handling of water main failures, shifting towards a proactive approach.
The second document aims to enhance the prioritization of infrastructure maintenance by predicting the risk of failure proactively.

Sources: wm_01, wm_02, wm_03, wm_04
- Rationale: Fallback lexical check found weak overlap with the expected grounded answer.

#### q18 - mixed

- Label: partially_grounded
- Question: Which document uses temporal cross-validation, and which one reports an R^2 of about 0.87?
- Answer: Not enough information in the provided context.

Sources: crli_08, crli_09, crli_10, wm_08
- Rationale: The answer refused even though some evidence was available.

#### q19 - mixed

- Label: partially_grounded
- Question: How do the two documents encode structural context when evaluating infrastructure risk or loss?
- Answer: Not enough information in the provided context.

Sources: crli_02, wm_02, wm_07, wm_10
- Rationale: The answer refused even though some evidence was available.

#### q20 - mixed

- Label: partially_grounded
- Question: Across both documents, what practical decision-making benefit is emphasized for utilities or city operations?
- Answer: Not enough information in the provided context.

Sources: wm_02, wm_04, wm_06, wm_09
- Rationale: The answer refused even though some evidence was available.

### web_search

#### q01 - available

- Label: grounded
- Question: What machine learning model performed best in the Syracuse water main break study?
- Answer: The gradient boosted decision trees performed best, achieving precision at 1% ([email protected]) of 0.62.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q02 - available

- Label: grounded
- Question: How is the prediction problem framed in the Syracuse paper, and why is that framing useful for the city?
- Answer: The prediction problem is framed as a binary classification problem to determine whether a water main break will occur on a given city block within the next three years. This framing allows the city of Syracuse to easily operationalize the model and plan infrastructure development for the next three years.

Sources: wm_arxiv_pdf, wm_kdd_page
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q03 - available

- Label: grounded
- Question: What two operational uses of the risk scores are described for the City of Syracuse?
- Answer: The two operational uses of the risk scores for the City of Syracuse are:
1) For preventative maintenance on the top 1% of the riskiest water mains.
2) To use the risk scores to coordinate with the Department of Public Works (DPW) during road construction and maintenance.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q04 - available

- Label: grounded
- Question: What does CRLI stand for, and how is it calculated?
- Answer: CRLI stands for Combined Real Loss Index.

The CRLI is calculated as the Geometric Mean of two key IWA metrics: Real losses per connection per day and Real losses per mains length.

Sources: crli_news_page, crli_web_pdf
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q05 - available

- Label: grounded
- Question: Why is CRLI presented as easier to use than ILI?
- Answer: CRLI is presented as easier to use than ILI because it combines Op27 and Op28 in a way that is more balanced for varying network structures, making it suitable for both urban and rural systems with different connection densities. Additionally, CRLI requires less data input since it only needs data utilities already track, whereas ILI might need pressure data or service connection length which are not always readily available.

Sources: crli_news_page, crli_web_pdf
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q06 - available

- Label: partially_grounded
- Question: What relationship between CRLI and ILI is reported in the presentation?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer refused even though some evidence was available.

#### q07 - missing

- Label: correctly_refused
- Question: What exact hyperparameters were used for the gradient boosted decision tree model?
- Answer: Not enough information in the provided context.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q08 - missing

- Label: correctly_refused
- Question: What annual dollar budget did Syracuse allocate to replace mains in the pilot?
- Answer: Not enough information in the provided context.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q09 - missing

- Label: correctly_refused
- Question: What CRLI reference bands have been validated for utilities outside Germany?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q10 - missing

- Label: correctly_refused
- Question: Which French utility first adopted CRLI after the conference?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q11 - missing

- Label: correctly_refused
- Question: What pressure-corrected formula replaced CRLI in the final policy recommendation?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q12 - conflicting

- Label: partially_grounded
- Question: How many breaks occurred on the riskiest 52 mains during the Syracuse pilot?
- Answer: Not enough information in the provided context.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The answer refused even though some evidence was available.

#### q13 - conflicting

- Label: hallucinated
- Question: What mean CRLI value is reported for Rhineland-Palatinate?
- Answer: The mean CRLI value reported for Rhineland-Palatinate is approximately 6.14.

Sources: crli_news_page, crli_web_pdf
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

#### q14 - conflicting

- Label: hallucinated
- Question: What mean CRLI value is reported for Saarland?
- Answer: The mean CRLI value reported for Saarland is approximately 7.79.

Sources: crli_news_page, crli_web_pdf
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

#### q15 - conflicting

- Label: hallucinated
- Question: Is the Syracuse system described only as a pilot, or as already deployed in the city?
- Answer: The Syracuse system is described as both deployed and in a pilot phase. It is currently deployed in the City of Syracuse, but it is also being conducted as a field trial to calculate the risk of failure for each city block over the period 2016-2018 using data up to the end of 2015.

Sources: wm_arxiv_abs, wm_arxiv_pdf, wm_kdd_page
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

#### q16 - mixed

- Label: partially_grounded
- Question: Which city deployed the water-main prediction model, and which two German regions are used in the CRLI evidence base?
- Answer: Syracuse, N.Y. deployed the water-main prediction model.

Sources: wm_arxiv_abs, wm_arxiv_pdf
- Rationale: Fallback lexical check found partial overlap with the reference answer.

#### q17 - mixed

- Label: partially_grounded
- Question: Compare the simplification strategy in both documents: what existing practice or metric is each document trying to improve on?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf, wm_arxiv_pdf
- Rationale: The answer refused even though some evidence was available.

#### q18 - mixed

- Label: partially_grounded
- Question: Which document uses temporal cross-validation, and which one reports an R^2 of about 0.87?
- Answer: Not enough information in the provided context.

Sources: wm_arxiv_abs, wm_arxiv_pdf
- Rationale: The answer refused even though some evidence was available.

#### q19 - mixed

- Label: partially_grounded
- Question: How do the two documents encode structural context when evaluating infrastructure risk or loss?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, crli_web_pdf, wm_arxiv_pdf
- Rationale: The answer refused even though some evidence was available.

#### q20 - mixed

- Label: partially_grounded
- Question: Across both documents, what practical decision-making benefit is emphasized for utilities or city operations?
- Answer: Not enough information in the provided context.

Sources: crli_web_pdf, wm_arxiv_abs
- Rationale: The answer refused even though some evidence was available.

### combined_sources

#### q01 - available

- Label: partially_grounded
- Question: What machine learning model performed best in the Syracuse water main break study?
- Answer: Not enough information in the provided context.

Sources: eval_water_main_breaks, wm_01, wm_05, wm_arxiv_abs, wm_arxiv_pdf
- Rationale: The answer refused even though some evidence was available.

#### q02 - available

- Label: grounded
- Question: How is the prediction problem framed in the Syracuse paper, and why is that framing useful for the city?
- Answer: The prediction problem is framed as a binary classification problem: whether a water main break will occur on a given city block within the next three years. This framing allows the city of Syracuse to easily operationalize the model and plan infrastructure development for the next three years.

Sources: eval_water_main_breaks, wm_06, wm_07, wm_kdd_page
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q03 - available

- Label: grounded
- Question: What two operational uses of the risk scores are described for the City of Syracuse?
- Answer: The two operational uses of the risk scores described for the City of Syracuse are:
1) For preventative maintenance on the top 1% of the riskiest water mains.
2) To use the risk scores to coordinate with the Department of Public Works as they do road construction and maintenance.

Sources: eval_water_main_breaks, wm_10, wm_13, wm_arxiv_pdf
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q04 - available

- Label: grounded
- Question: What does CRLI stand for, and how is it calculated?
- Answer: CRLI stands for Combined Real Loss Index. It is calculated as the geometric mean of two key IWA metrics: real losses per connection per day and real losses per mains length.

Sources: crli_04, crli_08, crli_news_page, crli_web_pdf, eval_crli
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q05 - available

- Label: partially_grounded
- Question: Why is CRLI presented as easier to use than ILI?
- Answer: 

Sources: crli_03, crli_06, crli_news_page, eval_crli
- Rationale: The model returned no substantive answer body even though the prompt expected one.

#### q06 - available

- Label: partially_grounded
- Question: What relationship between CRLI and ILI is reported in the presentation?
- Answer: CRLI responds strongly to ILI, as indicated by a fitted model with an R-squared value of 0.87.

Sources: crli_06, crli_07, crli_news_page, eval_crli
- Rationale: Fallback lexical check found partial overlap with the reference answer.

#### q07 - missing

- Label: correctly_refused
- Question: What exact hyperparameters were used for the gradient boosted decision tree model?
- Answer: Not enough information in the provided context.

Sources: eval_water_main_breaks, wm_01, wm_04, wm_arxiv_abs, wm_arxiv_pdf
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q08 - missing

- Label: correctly_refused
- Question: What annual dollar budget did Syracuse allocate to replace mains in the pilot?
- Answer: Not enough information in the provided context.

Sources: eval_water_main_breaks, wm_01, wm_13, wm_arxiv_abs
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q09 - missing

- Label: correctly_refused
- Question: What CRLI reference bands have been validated for utilities outside Germany?
- Answer: Not enough information in the provided context.

Sources: crli_01, crli_12, crli_news_page, crli_web_pdf, eval_crli
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q10 - missing

- Label: correctly_refused
- Question: Which French utility first adopted CRLI after the conference?
- Answer: Not enough information in the provided context.

Sources: crli_02, crli_03, crli_news_page, crli_web_pdf, eval_crli
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q11 - missing

- Label: correctly_refused
- Question: What pressure-corrected formula replaced CRLI in the final policy recommendation?
- Answer: Not enough information in the provided context.

Sources: crli_02, crli_03, crli_news_page, crli_web_pdf, eval_crli
- Rationale: The answer refused and the question belongs to the missing-information class.

#### q12 - conflicting

- Label: partially_grounded
- Question: How many breaks occurred on the riskiest 52 mains during the Syracuse pilot?
- Answer: Not enough information in the provided context.

Sources: eval_water_main_breaks, wm_11, wm_12, wm_arxiv_abs, wm_kdd_page
- Rationale: The answer refused even though some evidence was available.

#### q13 - conflicting

- Label: partially_grounded
- Question: What mean CRLI value is reported for Rhineland-Palatinate?
- Answer: Not enough information in the provided context.

Sources: crli_08, crli_09, crli_news_page, eval_crli
- Rationale: The answer refused even though some evidence was available.

#### q14 - conflicting

- Label: partially_grounded
- Question: What mean CRLI value is reported for Saarland?
- Answer: Not enough information in the provided context.

Sources: crli_10, crli_11, crli_news_page, eval_crli
- Rationale: The answer refused even though some evidence was available.

#### q15 - conflicting

- Label: hallucinated
- Question: Is the Syracuse system described only as a pilot, or as already deployed in the city?
- Answer: The Syracuse system is described as both deployed in the city and undergoing a field trial.

Sources: eval_water_main_breaks, wm_09, wm_13, wm_arxiv_abs, wm_kdd_page
- Rationale: The question is conflict-based, but the answer does not clearly acknowledge the conflict.

#### q16 - mixed

- Label: grounded
- Question: Which city deployed the water-main prediction model, and which two German regions are used in the CRLI evidence base?
- Answer: The city that deployed the water-main prediction model is Syracuse.

Two German regions used in the CRLI evidence base are Rhineland-Palatinate and Saarland.

Sources: eval_crli, eval_water_main_breaks, wm_03, wm_05, wm_arxiv_abs
- Rationale: Fallback lexical check found substantial overlap with the reference answer.

#### q17 - mixed

- Label: partially_grounded
- Question: Compare the simplification strategy in both documents: what existing practice or metric is each document trying to improve on?
- Answer: Document 1 is trying to improve on the traditional real losses per mains length metric by promoting the CRLI as a more nuanced alternative.

Document 2 is trying to improve on current heuristics used by experts for predicting water main breaks through a binary classification approach.

Sources: crli_news_page, crli_web_pdf, eval_crli, eval_water_main_breaks, wm_01, wm_02
- Rationale: Fallback lexical check found partial overlap with the reference answer.

#### q18 - mixed

- Label: partially_grounded
- Question: Which document uses temporal cross-validation, and which one reports an R^2 of about 0.87?
- Answer: The document that uses temporal cross-validation is:

Sources: crli_08, eval_water_main_breaks, wm_08, wm_arxiv_pdf
- Rationale: Fallback lexical check found partial overlap with the reference answer.

#### q19 - mixed

- Label: partially_grounded
- Question: How do the two documents encode structural context when evaluating infrastructure risk or loss?
- Answer: Not enough information in the provided context.

Sources: crli_news_page, eval_crli, wm_02, wm_07
- Rationale: The answer refused even though some evidence was available.

#### q20 - mixed

- Label: partially_grounded
- Question: Across both documents, what practical decision-making benefit is emphasized for utilities or city operations?
- Answer: The emphasis on practical decision-making benefit for utilities or city operations is the ability to enable more robust data collection and better-informed decisions without requiring complex data.

Sources: crli_web_pdf, eval_crli, eval_water_main_breaks, wm_02, wm_09
- Rationale: Fallback lexical check found partial overlap with the reference answer.
