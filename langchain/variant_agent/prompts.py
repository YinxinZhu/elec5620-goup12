from langchain_core.prompts import ChatPromptTemplate


KNOWLEDGE_POINT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are an experienced driving theory examiner. "
                "Read the learner's question and concisely identify the core knowledge point it tests. "
                "Detect the language of the question and respond entirely in that language. "
                "Return strict JSON with keys `knowledge_point_name` (short phrase) and "
                "`knowledge_point_summary` (one short paragraph)."
            ),
        ),
        ("human", "{original_question}"),
    ]
)


VARIATION_PLAN_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are planning assessment variants for the Australian DKT written exam. "
                "Given the knowledge point and the required number of variants, outline how each question "
                "will differ (scenario change, question framing, numbers, etc.). "
                "Keep the plan short, stay in the same language as the knowledge point, and return JSON "
                "with an array `variations`, each item containing `variation_type` and `focus` strings."
            ),
        ),
        (
            "human",
            (
                "Knowledge point name: {knowledge_point_name}\n"
                "Knowledge point summary: {knowledge_point_summary}\n"
                "Requested variants: {variant_count}\n"
                "Original question:\n{original_question}"
            ),
        ),
    ]
)


VARIANT_GENERATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are generating a single-choice driving theory question variant. "
                "Use the supplied knowledge point and variation focus to craft one new question. "
                "The question must stay in the same language as the original question. "
                "Return strict JSON with keys: `prompt`, `option_a`, `option_b`, `option_c`, "
                "`option_d`, `correct_option`, and `explanation`. "
                "Exactly four options labelled A-D must be produced. "
                "Ensure the explanation succinctly justifies the correct option."
            ),
        ),
        (
            "human",
            (
                "Knowledge point: {knowledge_point_name}\n"
                "Summary: {knowledge_point_summary}\n"
                "Variation type: {variation_type}\n"
                "Focus guidance: {focus}\n"
                "Original question:\n{original_question}"
            ),
        ),
    ]
)


VARIANT_VALIDATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are validating an Australian DKT multiple-choice question. "
                "Return JSON with keys `is_valid` (boolean) and `feedback` (string). "
                "Mark invalid if any option is missing, duplicated, or if the explanation does not "
                "justify the answer. Keep feedback concise and in the same language."
            ),
        ),
        (
            "human",
            (
                "Question to review:\n"
                "Prompt: {prompt}\n"
                "A: {option_a}\n"
                "B: {option_b}\n"
                "C: {option_c}\n"
                "D: {option_d}\n"
                "Correct option: {correct_option}\n"
                "Explanation: {explanation}"
            ),
        ),
    ]
)

