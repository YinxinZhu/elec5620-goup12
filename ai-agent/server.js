const express = require('express');
const axios = require('axios');
const dotenv = require('dotenv');

dotenv.config();

const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
const OPENAI_BASE_URL = process.env.OPENAI_BASE_URL || 'https://api.openai.com/v1';
const OPENAI_MODEL = process.env.OPENAI_MODEL || 'gpt-5-mini';
const PORT = process.env.PORT || 18899; // Default port 18899, can be specified in env file.
const AUTH_BEARER = process.env.AUTH_BEARER || '9786534210';
const LOG_OPENAI_RESPONSE = process.env.LOG_OPENAI_RESPONSE === 'true';

if (!OPENAI_API_KEY) {
  console.error('Missing OPENAI_API_KEY in environment variables.');
  process.exit(1);
}

const app = express();
// Guard against oversized payloads while accepting JSON bodies.
app.use(express.json({ limit: '1mb' }));

// [1] POST /api/generateVariant - orchestrates validation, OpenAI call, and response shaping.
app.post('/api/generateVariant', async (req, res) => {
  const authHeader = req.headers.authorization;
  const providedToken = typeof authHeader === 'string' && authHeader.startsWith('Bearer ')
    ? authHeader.slice('Bearer '.length).trim()
    : null;

  // Enforce simple bearer token authentication.
  if (!providedToken || providedToken !== AUTH_BEARER) {
    return res.status(401).json({ error: 'Unauthorized request.' });
  }

  const requestStart = process.hrtime.bigint();
  const requestIp = req.ip || req.socket?.remoteAddress || 'unknown';
  const userAgent = req.get('user-agent') || 'unknown';
  console.log(`[Request] ip=${requestIp} ua=${userAgent}`);

  const { question, num } = req.body || {};

  // Reject empty or non-string question payloads early.
  if (typeof question !== 'string' || !question.trim()) {
    return res.status(400).json({ error: '`question` must be a non-empty string.' });
  }

  let variantCount = Number.isInteger(num) ? num : undefined;
  if (variantCount === undefined) {
    variantCount = 3;
  }

  // Enforce the 1-5 variant contract to keep costs predictable.
  if (!Number.isInteger(variantCount) || variantCount < 1 || variantCount > 5) {
    return res.status(400).json({ error: '`num` must be an integer between 1 and 5.' });
  }

  const prompt = buildPrompt(question, variantCount);

  let usageSummary = null;

  try {
    // Forward the crafted prompt to OpenAI's Responses API.
    const apiResponse = await axios.post(
      `${OPENAI_BASE_URL}/responses`,
      {
        model: OPENAI_MODEL,
        reasoning: { effort: "low" }, // Reasoning setting, supported values are: 'low', 'medium', and 'high'."
        input: prompt
      },
      {
        headers: {
          Authorization: `Bearer ${OPENAI_API_KEY}`,
          'Content-Type': 'application/json'
        },
        timeout: 30000  // 30 seconds to time out
      }
    );

    // Safely drill into the responses array for the model's JSON string.
    const outputText = extractTextFromResponse(apiResponse.data);

    if (LOG_OPENAI_RESPONSE) {
      console.log(
        '[OpenAI Response]',
        JSON.stringify(apiResponse.data, null, 2)
      );
    }

    if (!outputText) {
      throw new Error('Missing content in OpenAI response.');
    }

    let parsed;
    try {
      // Enforce JSON-only replies to guarantee a stable downstream contract.
      parsed = JSON.parse(outputText);
    } catch (parseError) {
      throw new Error(`Unable to parse model response as JSON: ${parseError.message}`);
    }

    const elapsedMs = Number(process.hrtime.bigint() - requestStart) / 1e6;
    usageSummary = normaliseUsage(apiResponse.data?.usage);
    parsed.time = Math.round(elapsedMs);
    parsed.usage = usageSummary; // Addusage

    const variantTotal = Array.isArray(parsed.variant_questions) ? parsed.variant_questions.length : 0;
    const knowledgePoint = parsed.knowledge_point_name || 'N/A';

    console.log(
      `[Variant Completed] count=${variantTotal} duration=${elapsedMs.toFixed(0)}ms knowledge="${knowledgePoint}" tokens(in=${usageSummary.input_tokens}, out=${usageSummary.output_tokens}, reasoning=${usageSummary.reasoning_tokens}, total=${usageSummary.total_tokens})`
    );

    return res.json(parsed);
  } catch (error) {
    const status = error.response?.status ?? 500;
    const message =
      error.response?.data?.error?.message ||
      error.response?.data?.message ||
      error.message ||
      'Unexpected error';

    console.error('OpenAI proxy error:', message);

    const elapsedMs = Number(process.hrtime.bigint() - requestStart) / 1e6;
    const tokenDetails = usageSummary
      ? ` tokens(in=${usageSummary.input_tokens}, out=${usageSummary.output_tokens}, reasoning=${usageSummary.reasoning_tokens}, total=${usageSummary.total_tokens})`
      : '';
    console.error(
      `[Variant Failed] duration=${elapsedMs.toFixed(0)}ms${tokenDetails} reason=${message}`
    );

    if (status >= 400 && status < 500) {
      return res.status(status).json({ error: message });
    }

    return res.status(500).json({ error: 'Failed to generate question variants.' });
  }
});

// [2] Boot the HTTP server for client consumption.
app.listen(PORT, () => {
  console.log(`AI variant generator running on port ${PORT}`);
});

// [3] buildPrompt - prepare deterministic instructions for the model.
function buildPrompt(question, variantCount) {
  return [
    'You are an expert curriculum designer for the Australian DKT learner driver theory test.',
    'Detect the primary language used in the provided question and respond entirely in that language.',
    'Generate question variants that assess the same knowledge area while changing wording and scenario.',
    'Each variant must be a single-choice question with exactly four options labelled A, B, C, and D.',
    `Produce exactly ${variantCount} unique variants and keep the cognitive load similar to the source question.`,
    'Do not mention OpenAI, AI models, or that the content was generated.',
    'Return a JSON object with the following schema:',
    '{',
    '  "knowledge_point_name": string,             // concise knowledge point name',
    '  "knowledge_point_summary": string,          // short paragraph describing the knowledge point',
    '  "variant_questions": [',
    '    {',
    '      "prompt": string,',
    '      "option_a": string,',
    '      "option_b": string,',
    '      "option_c": string,',
    '      "option_d": string,',
    '      "correct_option": "A" | "B" | "C" | "D",',
    '      "explanation": string',
    '    }',
    '  ]',
    '}',
    'Ensure all options are plausible and the explanation justifies the correct answer succinctly.',
    'Here is the source question block:',
    '"""',
    question.trim(),
    '"""'
  ].join('\n');
}

// [4] extractTextFromResponse - normalise the Responses API payload shape.
function extractTextFromResponse(payload) {
  if (!payload) {
    return undefined;
  }

  if (typeof payload.output_text === 'string' && payload.output_text.trim()) {
    return payload.output_text;
  }

  if (Array.isArray(payload.output)) {
    for (const item of payload.output) {
      if (item?.type === 'message' && Array.isArray(item.content)) {
        for (const block of item.content) {
          if (block?.type === 'output_text' && typeof block.text === 'string' && block.text.trim()) {
            return block.text;
          }
        }
      }
      if (
        item?.type === 'output_text' &&
        typeof item.text === 'string' &&
        item.text.trim()
      ) {
        return item.text;
      }
    }
  }

  return undefined;
}

// [5] normaliseUsage - collapse OpenAI usage details into a consistent shape.
function normaliseUsage(usage) {
  const toNumber = (value) => {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === 'string' && value.trim() && !Number.isNaN(Number(value))) {
      return Number(value);
    }
    return 0;
  };

  return {
    input_tokens: toNumber(usage?.input_tokens),
    output_tokens: toNumber(usage?.output_tokens),
    reasoning_tokens: toNumber(
      usage?.output_tokens_details?.reasoning_tokens ?? usage?.reasoning_tokens
    ),
    total_tokens: toNumber(usage?.total_tokens)
  };
}
