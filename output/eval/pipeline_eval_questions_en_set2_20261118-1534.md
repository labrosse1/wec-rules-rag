# Retrieval evaluation – full pipeline 

- Date: 2026-11-18 15:34
- Questions: `eval/eval_questions_en_set2.jsonl` (50: 40 with expected articles, 10 off-topic, 10 follow-ups)
- Index: voyage-4-lite (1024 dims), built 2026-11-04
- Pipeline: rewriting of follow-ups → vector + BM25 (reciprocal rank fusion) → 10 candidates → rerank-3-lite → 5 articles; no relevance threshold

**Hit@5 (articles handed to the LLM): 95% (38/40) – threshold 90% – PASS**

| Metric | Full pipeline | Vector only (baseline) |
|---|---|---|
| Hit@5 | 95% | 92% |
| Rank 1 | 95% | 90% |
| Candidate recall@10 | 95% | – |

Candidate pool (ADR-004): expected article missing from the 10 candidates for 2 question(s) – raise the pool to 20.

## By question type

| Type | Questions | Hit@5 | Rank 1 | Baseline hit@5 |
|---|---|---|---|---|
| follow_up | 10 | 100% | 100% | 100% |
| regulation | 30 | 93% | 93% | 90% |

## Misses (2)

- **s05** (regulation) Can a team add fuel to a car that has stopped out on the circuit?
  - expected 9.1.5: not among the 10 candidates
  - handed: 12.2.2, 12.3.1, 12.2.1, APPENDIX 8-5, 14.6.5
- **s06** (regulation) If a car breaks down on the circuit, can the team come and fix it?
  - expected 12.3.2, 9.1.6: not among the 10 candidates
  - handed: 9.1.9, 6.4.6, 12.3.1, 15.1.3, 14.4.2

## Long articles 

- s49: expected 12.2.2 – rank after reranking 1 ✓

## Calibration data for the relevance threshold (best reranker score)

- In-scope questions (40): min 0.673 · p10 0.738 · median 0.847 · p90 0.907 · max 0.924
- Off-topic questions (10): min 0.411 · p10 0.412 · median 0.537 · p90 0.661 · max 0.678

| Threshold | In-scope refused | Off-topic still answered |
|---|---|---|
| 0.41 | 0/40 | 10/10 |
| 0.43 | 0/40 | 8/10 |
| 0.47 | 0/40 | 6/10 |
| 0.49 | 0/40 | 5/10 |
| 0.54 | 0/40 | 4/10 |
| 0.60 | 0/40 | 2/10 |
| 0.66 | 0/40 | 2/10 |
| 0.67 | 0/40 | 1/10 |
| 0.68 | 1/40 | 0/10 |
| 0.71 | 2/40 | 0/10 |
| 0.72 | 2/40 | 0/10 |
| 0.73 | 3/40 | 0/10 |
| 0.74 | 5/40 | 0/10 |
| 0.77 | 8/40 | 0/10 |
| 0.78 | 10/40 | 0/10 |
| 0.80 | 11/40 | 0/10 |
| 0.81 | 13/40 | 0/10 |
| 0.82 | 16/40 | 0/10 |
| 0.83 | 17/40 | 0/10 |
| 0.84 | 20/40 | 0/10 |
| 0.85 | 22/40 | 0/10 |
| 0.86 | 22/40 | 0/10 |
| 0.87 | 25/40 | 0/10 |
| 0.88 | 27/40 | 0/10 |
| 0.89 | 28/40 | 0/10 |
| 0.90 | 34/40 | 0/10 |
| 0.91 | 36/40 | 0/10 |
| 0.92 | 36/40 | 0/10 |

ADR-004: place the threshold between the two groups, on the low side (refusing a valid question is worse than handing a weak article).

## Off-topic questions

- s31 [0.544] Who won the 2025 24 Hours of Le Mans? → 15.3.1, APPENDIX 2-1, 3.1.3, 1.1, 1.2.4
- s32 [0.470] How much horsepower does a Hypercar have? → 6.2.2, APPENDIX 2-2, 6.2.1, 13.3.2, 3.2.3
- s33 [0.411] Where can I buy tickets for the WEC race at Spa? → APPENDIX 2-1, APPENDIX 9-1.13, APPENDIX 2-3, 6.5.4, 6.5.3
- s34 [0.596] Which manufacturers are racing in the Hypercar class this year? → 15.2.2, 3.2.3, 15.2.1, APPENDIX 9-1.3, APPENDIX 9-1.10
- s35 [0.490] How long is a lap of the Circuit de la Sarthe? → 14.2.4, 15.3.1, 14.6.7, 1.4.1, 14.6.8
- s36 [0.661] Who is the current WEC Hypercar world champion? → APPENDIX 3-3, 15.3.6, 15.2.2, 1.1, 15.3.5
- s37 [0.678] How much does it cost to buy a Hypercar? → APPENDIX 2-2, APPENDIX 2-5, 13.3.2, APPENDIX 2-3, APPENDIX 9-1.9
- s38 [0.431] How does DRS work in Formula 1? → 13.2.2, 11.2.4, 10.2.2, 14.4.2, 15.1.3
- s39 [0.537] How do I become a marshal at a WEC race? → 9.1.7, 1.3.2, 11.2.4, 7.3.6, 14.3.1
- s40 [0.412] Which TV channel shows the WEC races? → APPENDIX 3-FIG appendix-3-overalls, 4.3.2, APPENDIX 9-1.16, APPENDIX 9-1.18, APPENDIX 3-FIG appendix-3-lmgt3-stickers

## Follow-up rewriting

- **s41** And for LMGT3? ✓
  - rewritten: How many dry-weather tyres can an LMGT3 use for qualifying and the race at a 6-hour race?
  - expected:  How many dry-weather tyres can an LMGT3 car use for qualifying and the race at a 6-hour race?
- **s42** What about at Le Mans? ✓
  - rewritten: How many points does the winner score at Le Mans in the FIA World Endurance Championship?
  - expected:  How many points does the winner of the 24 Hours of Le Mans score?
- **s43** Can I still go into the pits? ✓
  - rewritten: Can you still go into the pits under a Full Course Yellow in the FIA WEC?
  - expected:  Can a car enter the pits during a Full Course Yellow?
- **s44** And what's the penalty if I go over it in the race? ✓
  - rewritten: What is the penalty for exceeding the pit lane speed limit during a race in the FIA World Endurance Championship?
  - expected:  What is the penalty for speeding in the pit lane during the race?
- **s45** And can a Bronze driver be in the crew? ✓
  - rewritten: Can a Bronze driver be in a Hypercar crew?
  - expected:  Can a Bronze driver be part of a Hypercar crew?
- **s46** When and where is it this year? ✓
  - rewritten: When and where is the FIA World Endurance Championship Prologue test this year?
  - expected:  When and where is the 2026 Prologue test?
- **s47** Can a team appeal it? ✓
  - rewritten: Can a team appeal a Stop & Go penalty in the FIA World Endurance Championship?
  - expected:  Can a Stop & Go penalty be appealed?
- **s48** And to appeal? ✓
  - rewritten: How much does it cost to lodge an appeal in the FIA World Endurance Championship?
  - expected:  How much is the appeal deposit?
- **s49** Are they allowed to use tools while refuelling? ✓
  - rewritten: Are people working on the car allowed to use tools while refuelling during an FIA WEC pit stop?
  - expected:  Can mechanics use tools while the car is being refuelled during a pit stop?
- **s50** And in a 10-hour race? ✓
  - rewritten: What is the minimum driving time for a Bronze driver in a 10-hour LMGT3 race?
  - expected:  What is the minimum driving time for a Bronze driver in a 10-hour LMGT3 race?
