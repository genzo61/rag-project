# Math Tool Evaluation Report

Generated: 2026-05-05 13:49 UTC

## Scope

- Goal: measure how reliably different model sizes use a Python-based math tool through orchestrator-driven tool calling.
- Models tested: 3B, 7B, and 7B+.
- Total test cases: 20.
- Task types: arithmetic, multi-step calculations, structured numeric tasks, insufficient-input/refusal cases, and conceptual control questions.

## Integration Flow

1. The user asks a mathematical question.
2. The orchestrator sends the question to the model for routing.
3. The model decides whether the Python math tool is required.
4. If math is required, the model returns a structured tool request.
5. The orchestrator validates the request and normalizes small schema mismatches when possible.
6. The orchestrator calls the Python math tool.
7. The math tool returns a deterministic result.
8. The orchestrator sends the tool result back to the model.
9. The model generates the final user-facing answer using the tool result.

## Summary

| Tier | Model | Tool choice accuracy | Tool-call recall | Raw tool-input accuracy | Normalized tool-input usability | Final answer accuracy | Integration success |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen 2.5 3B | `qwen2.5:3b` | 55.0% | 56.2% | 25.0% | 56.2% | 60.0% | 60.0% |
| Qwen 2.5 7B | `qwen2.5:7b` | 85.0% | 93.8% | 62.5% | 93.8% | 85.0% | 85.0% |
| GPT-OSS 120B | `openai/gpt-oss-120b:free` | 90.0% | 100.0% | 93.8% | 100.0% | 90.0% | 90.0% |

## Latency

| Model | Avg Response Time | Min | Max | Practical Comment |
| --- | ---: | ---: | ---: | --- |
| Qwen 2.5 3B | 19.2s | 5.3s | 73.9s | Fast enough, but still unreliable |
| Qwen 2.5 7B | 41.4s | 22.3s | 128.9s | Smallest acceptable tier |
| GPT-OSS 120B | 18.2s | 7.2s | 43.7s | Best overall quality |

## Math Tool Schema

Request schema example for expression mode:

```json
{
  "mode": "expression",
  "expression": "(240 * 1.15) - 18"
}
```

Request schema example for structured mode:

```json
{
  "mode": "structured",
  "operation": "weighted_mean",
  "values": [78, 85, 92],
  "weights": [0.2, 0.3, 0.5]
}
```

Response schema example:

```json
{
  "ok": true,
  "mode": "structured",
  "operation": "weighted_mean",
  "result": 87.1,
  "formatted_result": "87.1"
}
```

## Recommendation

- Smallest acceptable model by this evaluation: **Qwen 2.5 7B**
- Acceptance heuristic used here: at least 80% tool-call recall and 80% end-to-end integration success.
- Practical takeaway: Qwen 2.5 7B is the minimum viable local tier, while GPT-OSS 120B shows the strongest overall tool behavior when a larger hosted model is acceptable.

## Failure Patterns

### Qwen 2.5 3B
- `bad_final_answer`: 8
- `bad_tool_input`: 12
- `missed_tool_call`: 7
- `unusable_tool_input`: 7

### Qwen 2.5 7B
- `bad_final_answer`: 3
- `bad_tool_input`: 6
- `missed_tool_call`: 1
- `unusable_tool_input`: 1

### GPT-OSS 120B
- `bad_final_answer`: 2
- `bad_tool_input`: 1

## Model Details

### Qwen 2.5 3B

- `mt01` `arithmetic`: What is 125 + 349?
  Final answer: The result of the calculation 125 + 349 is 474.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=False; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"expression","value":"125 + 349"}` -> normalized `{"mode": "expression", "value": "125 + 349", "expression": "125 + 349"}` -> result `{"ok": true, "mode": "expression", "result": 474.0, "formatted_result": "474", "explanation": "Evaluated expression: 125 + 349"}`
- `mt02` `arithmetic`: Calculate 17 * 23.
  Final answer: The result of the calculation 17 * 23 is 391.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=False; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"expression","value":"17 * 23"}` -> normalized `{"mode": "expression", "value": "17 * 23", "expression": "17 * 23"}` -> result `{"ok": true, "mode": "expression", "result": 391.0, "formatted_result": "391", "explanation": "Evaluated expression: 17 * 23"}`
- `mt03` `arithmetic`: Calculate 985 - 426.
  Final answer: The result of the calculation 985 - 426 is 559.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=False; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"expression","value":"985 - 426"}` -> normalized `{"mode": "expression", "value": "985 - 426", "expression": "985 - 426"}` -> result `{"ok": true, "mode": "expression", "result": 559.0, "formatted_result": "559", "explanation": "Evaluated expression: 985 - 426"}`
- `mt04` `arithmetic`: Calculate ((10 + 20 + 30) / 3) * 2.
  Final answer: The result of the calculation is 40.0.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"expression":"((10 + 20 + 30) / 3) * 2","mode":"expression"}` -> normalized `{"expression": "((10 + 20 + 30) / 3) * 2", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 40.0, "formatted_result": "40", "explanation": "Evaluated expression: ((10 + 20 + 30) / 3) * 2"}`
- `mt05` `multi_step`: A store sells 8 notebooks at $3.75 each and 5 pens at $1.20 each. What is the total sales amount?
  Final answer: [empty]
  Tool choice: missed_call; final_answer_correct=False; raw_tool_input_correct=False; normalized_tool_input_usable=False; integration_ok=False
- `mt06` `multi_step`: Increase 240 by 15%, then subtract 18. What is the final result?
  Final answer: [empty]
  Tool choice: missed_call; final_answer_correct=False; raw_tool_input_correct=False; normalized_tool_input_usable=False; integration_ok=False
- `mt07` `multi_step`: A car travels 180 km at 60 km/h and 120 km at 80 km/h. What is the average speed for the whole trip?
  Final answer: The average speed for the whole trip is approximately 66.67 km/h.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"expression","expression":"(180 + 120) / ((180 / 60) + (120 / 80))"}` -> normalized `{"mode": "expression", "expression": "(180 + 120) / ((180 / 60) + (120 / 80))"}` -> result `{"ok": true, "mode": "expression", "result": 66.66666666666667, "formatted_result": "66.6666666667", "explanation": "Evaluated expression: (180 + 120) / ((180 / 60) + (120 / 80))"}`
- `mt08` `multi_step`: Calculate the final price if the original price is 800 and the discount is 25%.
  Final answer: [empty]
  Tool choice: missed_call; final_answer_correct=False; raw_tool_input_correct=False; normalized_tool_input_usable=False; integration_ok=False
- `mt09` `multi_step`: Calculate density where mass = 50 kg and volume = 2 m^3.
  Final answer: None of the provided functions can calculate density directly. Density is calculated as mass divided by volume. Let me provide you with a formula for it.
The formula for density (D) is D = m / V, where m is mass and V is volume. Given that mass = 50 kg and volume = 2 m^3, we can calculate the density.
  Tool choice: missed_call; final_answer_correct=False; raw_tool_input_correct=False; normalized_tool_input_usable=False; integration_ok=False
- `mt10` `structured_numeric`: Find the arithmetic mean of 12, 18, 24, and 30.
  Final answer: The arithmetic mean of the numbers 12, 18, 24, and 30 is 21.0.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=False; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"structured","operation":"mean","values":[12,18,24,30]}` -> normalized `{"mode": "structured", "operation": "mean", "values": [12, 18, 24, 30], "numbers": [12, 18, 24, 30]}` -> result `{"ok": true, "mode": "structured", "operation": "mean", "result": 21.0, "formatted_result": "21"}`
- `mt11` `structured_numeric`: Find the weighted mean of 78, 85, and 92 with weights 0.2, 0.3, and 0.5.
  Final answer: The weighted mean of the values 78, 85, and 92 with their respective weights is 87.1.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"structured","operation":"weighted_mean","values":[78,85,92],"weights":[0.2,0.3,0.5]}` -> normalized `{"mode": "structured", "operation": "weighted_mean", "values": [78, 85, 92], "weights": [0.2, 0.3, 0.5]}` -> result `{"ok": true, "mode": "structured", "operation": "weighted_mean", "result": 87.1, "formatted_result": "87.1"}`
- `mt12` `structured_numeric`: What is the percentage change from 84 to 105?
  Final answer: [empty]
  Tool choice: missed_call; final_answer_correct=False; raw_tool_input_correct=False; normalized_tool_input_usable=False; integration_ok=False
- `mt13` `structured_numeric`: How many values in the list 4, 9, 12, 7, 15, 10, 22 are greater than 10?
  Final answer: [empty]
  Tool choice: missed_call; final_answer_correct=False; raw_tool_input_correct=False; normalized_tool_input_usable=False; integration_ok=False
- `mt14` `structured_numeric`: Calculate pressure using P = F / A where F = 100 and A = 5.
  Final answer: The calculated pressure P is 20.0 units.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"function":"UseFunction","mode":"expression","expression":"(100 / 5)"}` -> normalized `{"function": "UseFunction", "mode": "expression", "expression": "(100 / 5)"}` -> result `{"ok": true, "mode": "expression", "result": 20.0, "formatted_result": "20", "explanation": "Evaluated expression: (100 / 5)"}`
- `mt15` `insufficient_input`: Calculate pressure using P = F / A where F = 100 N.
  Final answer: No exact numeric result needed for this question as it does not require a calculation. The formula provided is correct and ready to be used with the given values.
  Tool choice: optional_skip; final_answer_correct=True; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=True
- `mt16` `conceptual`: What does the arithmetic mean represent?
  Final answer: The arithmetic mean represents the sum of a set of numbers divided by the count of numbers in the set.
  Tool choice: correct_skip; final_answer_correct=True; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=True
- `mt17` `conceptual`: Explain what pressure means.
  Final answer: Pressure is defined as the force applied per unit area over which the force is distributed. It is often measured in pascals (Pa), where 1 pascal equals 1 newton per square meter (N/m²). In everyday language, it can be thought of as "how hard something presses against a surface."
  Tool choice: correct_skip; final_answer_correct=True; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=True
- `mt18` `structured_numeric`: Find the median of 5, 8, 11, and 14.
  Final answer: The median of the numbers 5, 8, 11, and 14 is 9.5.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=False; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"structured","operation":"median","values":[5,8,11,14]}` -> normalized `{"mode": "structured", "operation": "median", "values": [5, 8, 11, 14], "numbers": [5, 8, 11, 14]}` -> result `{"ok": true, "mode": "structured", "operation": "median", "result": 9.5, "formatted_result": "9.5"}`
- `mt19` `structured_numeric`: What is 15% of 240?
  Final answer: [empty]
  Tool choice: missed_call; final_answer_correct=False; raw_tool_input_correct=False; normalized_tool_input_usable=False; integration_ok=False
- `mt20` `insufficient_input`: Calculate the weighted mean of 78 and 85 with weights 0.2 only.
  Final answer: [empty]
  Tool choice: optional_call; final_answer_correct=False; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=False
  Tool args: `{"values":[78,85],"weights":[0.2],"mode":"structured","operation":"weighted_mean"}` -> normalized `{"values": [78, 85], "weights": [0.2], "mode": "structured", "operation": "weighted_mean"}` -> result `{"ok": false, "mode": "structured", "error": "values and weights must have the same length"}`

### Qwen 2.5 7B

- `mt01` `arithmetic`: What is 125 + 349?
  Final answer: The result of 125 + 349 is 474.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"expression":"125 + 349","mode":"expression"}` -> normalized `{"expression": "125 + 349", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 474.0, "formatted_result": "474", "explanation": "Evaluated expression: 125 + 349"}`
- `mt02` `arithmetic`: Calculate 17 * 23.
  Final answer: The result of 17 multiplied by 23 is 391.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"expression","expression":"17 * 23"}` -> normalized `{"mode": "expression", "expression": "17 * 23"}` -> result `{"ok": true, "mode": "expression", "result": 391.0, "formatted_result": "391", "explanation": "Evaluated expression: 17 * 23"}`
- `mt03` `arithmetic`: Calculate 985 - 426.
  Final answer: The result of 985 - 426 is 559.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"expression","expression":"985 - 426"}` -> normalized `{"mode": "expression", "expression": "985 - 426"}` -> result `{"ok": true, "mode": "expression", "result": 559.0, "formatted_result": "559", "explanation": "Evaluated expression: 985 - 426"}`
- `mt04` `arithmetic`: Calculate ((10 + 20 + 30) / 3) * 2.
  Final answer: The result of the calculation \(((10 + 20 + 30) / 3) * 2\) is \(40\).
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"expression","expression":"(10 + 20 + 30) / 3 * 2"}` -> normalized `{"mode": "expression", "expression": "(10 + 20 + 30) / 3 * 2"}` -> result `{"ok": true, "mode": "expression", "result": 40.0, "formatted_result": "40", "explanation": "Evaluated expression: (10 + 20 + 30) / 3 * 2"}`
- `mt05` `multi_step`: A store sells 8 notebooks at $3.75 each and 5 pens at $1.20 each. What is the total sales amount?
  Final answer: The total sales amount is $36.00.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"expression","expression":"(8 * 3.75) + (5 * 1.20)"}` -> normalized `{"mode": "expression", "expression": "(8 * 3.75) + (5 * 1.20)"}` -> result `{"ok": true, "mode": "expression", "result": 36.0, "formatted_result": "36", "explanation": "Evaluated expression: (8 * 3.75) + (5 * 1.20)"}`
- `mt06` `multi_step`: Increase 240 by 15%, then subtract 18. What is the final result?
  Final answer: The final result after increasing 240 by 15% and then subtracting 18 is 258.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"expression","expression":"(240 * 1.15) - 18"}` -> normalized `{"mode": "expression", "expression": "(240 * 1.15) - 18"}` -> result `{"ok": true, "mode": "expression", "result": 258.0, "formatted_result": "258", "explanation": "Evaluated expression: (240 * 1.15) - 18"}`
- `mt07` `multi_step`: A car travels 180 km at 60 km/h and 120 km at 80 km/h. What is the average speed for the whole trip?
  Final answer: The average speed for the whole trip is 2.25 hours per km or approximately 0.42 km/h. However, to express it in a more conventional way, this means the average speed was about 42.22 km/h.
  Tool choice: correct_call; final_answer_correct=False; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=False
  Tool args: `{"expression":"(180 / 60 + 120 / 80) / 2","mode":"expression"}` -> normalized `{"expression": "(180 / 60 + 120 / 80) / 2", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 2.25, "formatted_result": "2.25", "explanation": "Evaluated expression: (180 / 60 + 120 / 80) / 2"}`
- `mt08` `multi_step`: Calculate the final price if the original price is 800 and the discount is 25%.
  Final answer: The formula to calculate the final price after a discount is: \( \text{Final Price} = \text{Original Price} - (\text{Original Price} \times \text{Discount}) \).

Given:
- Original Price = 800
- Discount = 25%

Let's compute the final price.
  Tool choice: missed_call; final_answer_correct=False; raw_tool_input_correct=False; normalized_tool_input_usable=False; integration_ok=False
- `mt09` `multi_step`: Calculate density where mass = 50 kg and volume = 2 m^3.
  Final answer: The density is 25 kg/m³.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"expression","expression":"50 / 2"}` -> normalized `{"mode": "expression", "expression": "50 / 2"}` -> result `{"ok": true, "mode": "expression", "result": 25.0, "formatted_result": "25", "explanation": "Evaluated expression: 50 / 2"}`
- `mt10` `structured_numeric`: Find the arithmetic mean of 12, 18, 24, and 30.
  Final answer: The arithmetic mean of the numbers 12, 18, 24, and 30 is 21.0.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=False; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"operation":"mean","numbers":[12,18,24,30]}` -> normalized `{"operation": "mean", "numbers": [12, 18, 24, 30], "mode": "structured"}` -> result `{"ok": true, "mode": "structured", "operation": "mean", "result": 21.0, "formatted_result": "21"}`
- `mt11` `structured_numeric`: Find the weighted mean of 78, 85, and 92 with weights 0.2, 0.3, and 0.5.
  Final answer: The weighted mean of the numbers 78, 85, and 92 with weights 0.2, 0.3, and 0.5 is 87.1.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=False; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"mode":"structured","values":[78,85,92],"weights":[0.2,0.3,0.5]}` -> normalized `{"mode": "structured", "values": [78, 85, 92], "weights": [0.2, 0.3, 0.5], "operation": "weighted_mean"}` -> result `{"ok": true, "mode": "structured", "operation": "weighted_mean", "result": 87.1, "formatted_result": "87.1"}`
- `mt12` `structured_numeric`: What is the percentage change from 84 to 105?
  Final answer: The percentage change from 84 to 105 is 25%.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"old_value":84,"new_value":105,"mode":"structured","operation":"percentage_change"}` -> normalized `{"old_value": 84, "new_value": 105, "mode": "structured", "operation": "percentage_change"}` -> result `{"ok": true, "mode": "structured", "operation": "percentage_change", "result": 25.0, "formatted_result": "25"}`
- `mt13` `structured_numeric`: How many values in the list 4, 9, 12, 7, 15, 10, 22 are greater than 10?
  Final answer: There are 3 values in the list that are greater than 10.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=False; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"threshold":10,"mode":"count_greater_than","values":[4,9,12,7,15,10,22]}` -> normalized `{"threshold": 10, "mode": "structured", "values": [4, 9, 12, 7, 15, 10, 22], "operation": "count_greater_than", "numbers": [4, 9, 12, 7, 15, 10, 22]}` -> result `{"ok": true, "mode": "structured", "operation": "count_greater_than", "result": 3.0, "formatted_result": "3"}`
- `mt14` `structured_numeric`: Calculate pressure using P = F / A where F = 100 and A = 5.
  Final answer: The pressure \( P \) is calculated as \( \frac{F}{A} = \frac{100}{5} = 20 \). Therefore, the pressure is 20 units.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"expression":"(100 / 5)","mode":"expression"}` -> normalized `{"expression": "(100 / 5)", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 20.0, "formatted_result": "20", "explanation": "Evaluated expression: (100 / 5)"}`
- `mt15` `insufficient_input`: Calculate pressure using P = F / A where F = 100 N.
  Final answer: To calculate the pressure \( P \) given a force \( F = 100 \, \text{N} \) and an area \( A \), we use the formula:

\[ P = \frac{F}{A} \]

However, you haven't provided the value of the area \( A \). Could you please specify the area in square meters? If no specific area
  Tool choice: optional_skip; final_answer_correct=True; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=True
- `mt16` `conceptual`: What does the arithmetic mean represent?
  Final answer: The arithmetic mean represents the sum of a set of numbers divided by the count of numbers in that set. It is often referred to as the average. The formula for the arithmetic mean of a list of numbers \( x_1, x_2, \ldots, x_n \) is:

\[
\text{mean} = \frac{x_1 + x_2 + \cd
  Tool choice: correct_skip; final_answer_correct=True; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=True
- `mt17` `conceptual`: Explain what pressure means.
  Final answer: Pressure is defined as force per unit area. It can be mathematically expressed as:

\[ P = \frac{F}{A} \]

where \( P \) is the pressure, \( F \) is the force applied, and \( A \) is the area over which the force is distributed.
  Tool choice: correct_skip; final_answer_correct=True; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=True
- `mt18` `structured_numeric`: Find the median of 5, 8, 11, and 14.
  Final answer: The median of the numbers 5, 8, 11, and 14 is 9.5.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=False; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"operation":"median","numbers":[5,8,11,14]}` -> normalized `{"operation": "median", "numbers": [5, 8, 11, 14], "mode": "structured"}` -> result `{"ok": true, "mode": "structured", "operation": "median", "result": 9.5, "formatted_result": "9.5"}`
- `mt19` `structured_numeric`: What is 15% of 240?
  Final answer: 15% of 240 is 36.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=False; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{"operation":"percentage_of","value":240,"percent":15}` -> normalized `{"operation": "percentage_of", "value": 240, "percent": 15, "expression": "240", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 240.0, "formatted_result": "240", "explanation": "Evaluated expression: 240"}`
- `mt20` `insufficient_input`: Calculate the weighted mean of 78 and 85 with weights 0.2 only.
  Final answer: The weighted mean of 78 and 85 with weights 0.2 and 1 is approximately 83.83.
  Tool choice: optional_call; final_answer_correct=False; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=False
  Tool args: `{"mode":"structured","values":[78,85],"weights":[0.2,1]}` -> normalized `{"mode": "structured", "values": [78, 85], "weights": [0.2, 1], "operation": "weighted_mean"}` -> result `{"ok": true, "mode": "structured", "operation": "weighted_mean", "result": 83.83333333333333, "formatted_result": "83.8333333333"}`

### GPT-OSS 120B

- `mt01` `arithmetic`: What is 125 + 349?
  Final answer: 125 + 349 = 474.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "expression": "125 + 349",
  "mode": "expression"
}` -> normalized `{"expression": "125 + 349", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 474.0, "formatted_result": "474", "explanation": "Evaluated expression: 125 + 349"}`
- `mt02` `arithmetic`: Calculate 17 * 23.
  Final answer: \(17 \times 23 = 391\)
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "expression": "17 * 23",
  "mode": "expression"
}` -> normalized `{"expression": "17 * 23", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 391.0, "formatted_result": "391", "explanation": "Evaluated expression: 17 * 23"}`
- `mt03` `arithmetic`: Calculate 985 - 426.
  Final answer: 559
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "expression": "985 - 426",
  "mode": "expression"
}` -> normalized `{"expression": "985 - 426", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 559.0, "formatted_result": "559", "explanation": "Evaluated expression: 985 - 426"}`
- `mt04` `arithmetic`: Calculate ((10 + 20 + 30) / 3) * 2.
  Final answer: The value is **40**.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "expression": "((10 + 20 + 30) / 3) * 2",
  "mode": "expression"
}` -> normalized `{"expression": "((10 + 20 + 30) / 3) * 2", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 40.0, "formatted_result": "40", "explanation": "Evaluated expression: ((10 + 20 + 30) / 3) * 2"}`
- `mt05` `multi_step`: A store sells 8 notebooks at $3.75 each and 5 pens at $1.20 each. What is the total sales amount?
  Final answer: The total sales amount is **$36**.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "expression": "8*3.75 + 5*1.20",
  "mode": "expression"
}` -> normalized `{"expression": "8*3.75 + 5*1.20", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 36.0, "formatted_result": "36", "explanation": "Evaluated expression: 8*3.75 + 5*1.20"}`
- `mt06` `multi_step`: Increase 240 by 15%, then subtract 18. What is the final result?
  Final answer: The final result is **258**.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "expression": "240 * 1.15 - 18",
  "mode": "expression"
}` -> normalized `{"expression": "240 * 1.15 - 18", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 258.0, "formatted_result": "258", "explanation": "Evaluated expression: 240 * 1.15 - 18"}`
- `mt07` `multi_step`: A car travels 180 km at 60 km/h and 120 km at 80 km/h. What is the average speed for the whole trip?
  Final answer: The average speed for the whole trip is **≈ 66.67 km/h**.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "expression": "300 / (180/60 + 120/80)",
  "mode": "expression"
}` -> normalized `{"expression": "300 / (180/60 + 120/80)", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 66.66666666666667, "formatted_result": "66.6666666667", "explanation": "Evaluated expression: 300 / (180/60 + 120/80)"}`
- `mt08` `multi_step`: Calculate the final price if the original price is 800 and the discount is 25%.
  Final answer: The final price is **600**.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "expression": "800 * (1 - 0.25)",
  "mode": "expression"
}` -> normalized `{"expression": "800 * (1 - 0.25)", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 600.0, "formatted_result": "600", "explanation": "Evaluated expression: 800 * (1 - 0.25)"}`
- `mt09` `multi_step`: Calculate density where mass = 50 kg and volume = 2 m^3.
  Final answer: The density is \( \displaystyle \frac{50\text{ kg}}{2\text{ m}^3}=25\text{ kg/m}^3\).
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "expression": "50/2",
  "mode": "expression"
}` -> normalized `{"expression": "50/2", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 25.0, "formatted_result": "25", "explanation": "Evaluated expression: 50/2"}`
- `mt10` `structured_numeric`: Find the arithmetic mean of 12, 18, 24, and 30.
  Final answer: The arithmetic mean is **21**.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "operation": "mean",
  "numbers": [12, 18, 24, 30],
  "mode": "structured"
}` -> normalized `{"operation": "mean", "numbers": [12, 18, 24, 30], "mode": "structured"}` -> result `{"ok": true, "mode": "structured", "operation": "mean", "result": 21.0, "formatted_result": "21"}`
- `mt11` `structured_numeric`: Find the weighted mean of 78, 85, and 92 with weights 0.2, 0.3, and 0.5.
  Final answer: The weighted mean is **87.1**.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "mode": "structured",
  "operation": "weighted_mean",
  "values": [78, 85, 92],
  "weights": [0.2, 0.3, 0.5]
}` -> normalized `{"mode": "structured", "operation": "weighted_mean", "values": [78, 85, 92], "weights": [0.2, 0.3, 0.5]}` -> result `{"ok": true, "mode": "structured", "operation": "weighted_mean", "result": 87.1, "formatted_result": "87.1"}`
- `mt12` `structured_numeric`: What is the percentage change from 84 to 105?
  Final answer: The percentage change from 84 to 105 is **25 %**.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "mode": "structured",
  "operation": "percentage_change",
  "old_value": 84,
  "new_value": 105
}` -> normalized `{"mode": "structured", "operation": "percentage_change", "old_value": 84, "new_value": 105}` -> result `{"ok": true, "mode": "structured", "operation": "percentage_change", "result": 25.0, "formatted_result": "25"}`
- `mt13` `structured_numeric`: How many values in the list 4, 9, 12, 7, 15, 10, 22 are greater than 10?
  Final answer: 3 values are greater than 10.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "mode": "structured",
  "operation": "count_greater_than",
  "numbers": [4, 9, 12, 7, 15, 10, 22],
  "threshold": 10
}` -> normalized `{"mode": "structured", "operation": "count_greater_than", "numbers": [4, 9, 12, 7, 15, 10, 22], "threshold": 10}` -> result `{"ok": true, "mode": "structured", "operation": "count_greater_than", "result": 3.0, "formatted_result": "3"}`
- `mt14` `structured_numeric`: Calculate pressure using P = F / A where F = 100 and A = 5.
  Final answer: The pressure is \(P = \frac{F}{A} = \frac{100}{5} = 20\) (units consistent with the given force and area).
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "expression": "100 / 5",
  "mode": "expression"
}` -> normalized `{"expression": "100 / 5", "mode": "expression"}` -> result `{"ok": true, "mode": "expression", "result": 20.0, "formatted_result": "20", "explanation": "Evaluated expression: 100 / 5"}`
- `mt15` `insufficient_input`: Calculate pressure using P = F / A where F = 100 N.
  Final answer: The pressure is  

\[
P=\frac{F}{A}=\frac{100\ \text{N}}{A}
\]

so you divide 100 N by the area \(A\) (in m²) to get the pressure in pascals (Pa).
  Tool choice: optional_skip; final_answer_correct=False; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=False
- `mt16` `conceptual`: What does the arithmetic mean represent?
  Final answer: The arithmetic mean (often just called the “average”) is the sum of a set of numbers divided by how many numbers are in the set. It represents the central or typical value of the data—i.e., the point at which the total “amount” of the data would be evenly distributed if each observation contributed equally. In other words, it’s the value you would get if you pooled all the quantities together and then split them into equal parts.
  Tool choice: correct_skip; final_answer_correct=True; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=True
- `mt17` `conceptual`: Explain what pressure means.
  Final answer: Pressure is the amount of force applied perpendicular to a surface per unit area of that surface. It quantifies how “intense” a force is over the area it acts on. Mathematically,  

\[
P = \frac{F}{A},
\]

where \(P\) is pressure, \(F\) is the normal force, and \(A\) is the area.  

- **Units:** In the SI system, pressure is measured in pascals (Pa), where \(1\,\text{Pa}=1\,\text{N/m}^2\). Other common units include atmospheres (atm), millimeters of mercury (mm Hg), and pounds per square inch (psi).  
- **Direction:** Pressure acts equally in all directions at a point within a fluid (hydrostatic pressure) and always normal (perpendicular) to a surface.  
- **Examples:**  
  - Atmospheric pressure (~101 kPa) is the weight of the air above us per unit area.  
  - Tire pressure (~30 psi) indicates how much force the air inside exerts on the tire walls per square inch.  

In essence, pressure tells you how concentrated a force is over an area; a larger force over a small area yields high pressure, while the same force spread over a larger area results in lower pressure.
  Tool choice: correct_skip; final_answer_correct=True; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=True
- `mt18` `structured_numeric`: Find the median of 5, 8, 11, and 14.
  Final answer: The median of the numbers 5, 8, 11, 14 is **9.5**.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=False; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "operation": "median",
  "numbers": [5, 8, 11, 14]
}` -> normalized `{"operation": "median", "numbers": [5, 8, 11, 14], "mode": "structured"}` -> result `{"ok": true, "mode": "structured", "operation": "median", "result": 9.5, "formatted_result": "9.5"}`
- `mt19` `structured_numeric`: What is 15% of 240?
  Final answer: 15 % of 240 is **36**.
  Tool choice: correct_call; final_answer_correct=True; raw_tool_input_correct=True; normalized_tool_input_usable=True; integration_ok=True
  Tool args: `{
  "mode": "structured",
  "operation": "percentage_of",
  "value": 240,
  "percent": 15
}` -> normalized `{"mode": "structured", "operation": "percentage_of", "value": 240, "percent": 15, "expression": "240"}` -> result `{"ok": true, "mode": "structured", "operation": "percentage_of", "result": 36.0, "formatted_result": "36"}`
- `mt20` `insufficient_input`: Calculate the weighted mean of 78 and 85 with weights 0.2 only.
  Final answer: The weighted mean is **81.5**.
  Tool choice: optional_call; final_answer_correct=False; raw_tool_input_correct=None; normalized_tool_input_usable=None; integration_ok=False
  Tool args: `{
  "operation": "weighted_mean",
  "values": [78, 85],
  "weights": [0.2, 0.2]
}` -> normalized `{"operation": "weighted_mean", "values": [78, 85], "weights": [0.2, 0.2], "mode": "structured"}` -> result `{"ok": true, "mode": "structured", "operation": "weighted_mean", "result": 81.5, "formatted_result": "81.5"}`
