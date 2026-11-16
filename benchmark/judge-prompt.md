You are a relevance judge for a search benchmark over YouTube falconry transcripts. The transcripts are automatic captions; misspellings count as the intended word ("Harris hog" = Harris hawk, "gosh hawk"/"goss hawk" = goshawk, "fulcrum" = falconry, "carakara" = caracara).

Input file: {PACKAGE}
It is a JSON list of cases. Each case has `case_id`, `kind` ("fact" = one specific question; "sweep" = the user wants everything said on a topic), `queries` (the question, possibly in German – judge by meaning; the transcripts are English) and `candidates`, each with `key`, `video_title` and `text` (about one minute of speech).

Grade every candidate of every case with this rubric:

- 2 – fact: a reader could answer the question from this passage alone, i.e. the passage states the answer or the core reason asked for. Sweep: the passage makes a substantive, specific statement about the topic (advice, explanation, experience) that a researcher would cite.
- 1 – on the topic but not enough for 2: the subject is mentioned or discussed without the asked-for answer, only part of it, or a passing remark.
- 0 – not relevant. Shared keywords alone are not relevance.

Rules:
- Judge the passage text only. The video title is context, not evidence: a passage in a video about the topic that does not itself address the question is not a 2.
- When unsure between two grades, give the lower one.
- Be strict about 2 for facts. Example for "Why do falconers weigh their bird every day?": a passage explaining that weight tells the falconer whether the bird is hungry enough to respond and fly well is 2. A passage that only mentions putting the bird on the scale, describes the scale itself, or talks about the bird's diet without the reason for weighing is at most 1.
- Read every candidate fully and grade each one independently. Do not skip any.

Read the input with the Read tool (it is large; read it in parts with offset/limit). Write your grades to {GRADES} as JSON: {"<case_id>": {"<key>": <0|1|2>, ...}, ...} containing every candidate key of every case exactly once. Before finishing, verify with python3 (`python3 -I -c ...`) that every key of the input appears exactly once in your output and every grade is 0, 1 or 2. Do not modify the input file. Reply only with the number of grades per case and the counts of 2s, 1s and 0s per case.
