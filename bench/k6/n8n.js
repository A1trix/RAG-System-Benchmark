import http from "k6/http";
import { check } from "k6";
import { SharedArray } from "k6/data";
import exec from "k6/execution";
import { Counter, Trend } from "k6/metrics";

const resp_body_bytes = new Trend("resp_body_bytes");
const answer_chars = new Trend("answer_chars");

// Frontier (constant-arrival-rate) measure-window metrics.
// Only emitted during the "measure" scenario.
const latency_measure_ms = new Trend("latency_measure_ms", true);
const attempts_measure = new Counter("attempts_measure");
const successes_measure = new Counter("successes_measure");
const timeouts_measure = new Counter("timeouts_measure");
const errors_total_measure = new Counter("errors_total_measure");
const errors_non_timeout_measure = new Counter("errors_non_timeout_measure");
const http_429_measure = new Counter("http_429_measure");
const http_5xx_measure = new Counter("http_5xx_measure");
const http_non_200_measure = new Counter("http_non_200_measure");

// Prompt-tagged measure-window counters.
// Only emitted during the "measure" scenario.
const attempts_measure_prompt = new Counter("attempts_measure_prompt");
const successes_measure_prompt = new Counter("successes_measure_prompt");
const timeouts_measure_prompt = new Counter("timeouts_measure_prompt");
const errors_non_timeout_measure_prompt = new Counter("errors_non_timeout_measure_prompt");

// Measure-window failure taxonomy counters (untagged totals).
// Only emitted during the "measure" scenario.
const contract_fail_measure = new Counter("contract_fail_measure");
const empty_answer_measure = new Counter("empty_answer_measure");
const citation_missing_measure = new Counter("citation_missing_measure");
const json_parse_fail_measure = new Counter("json_parse_fail_measure");
const transport_error_non_timeout_measure = new Counter("transport_error_non_timeout_measure");
// Token usage per successful request (measure window only).
// Used for correlation analysis with latency.
const tokens_prompt = new Trend("tokens_prompt");
const tokens_completion = new Trend("tokens_completion");
const tokens_total = new Trend("tokens_total");

function extractAnswer(body) {
  if (!body) return "";

  function fromObj(obj) {
    if (!obj) return "";
    if (typeof obj === "string") return obj;
    if (typeof obj !== "object" || Array.isArray(obj)) return "";

    const keys = ["answer", "output", "text", "response", "result"];
    for (const k of keys) {
      if (typeof obj[k] === "string" && obj[k].trim().length > 0) return obj[k];
    }
    // Common n8n item envelope: { json: {...} }
    if (obj.json && typeof obj.json === "object" && !Array.isArray(obj.json)) {
      for (const k of keys) {
        if (
          typeof obj.json[k] === "string" &&
          obj.json[k].trim().length > 0
        )
          return obj.json[k];
      }
    }
    return "";
  }

  try {
    const obj = JSON.parse(body);
    if (typeof obj === "string") return obj;
    if (Array.isArray(obj)) {
      for (const item of obj) {
        const out = fromObj(item);
        if (out && out.trim().length > 0) return out;
      }
      return "";
    }
    if (obj && typeof obj === "object") {
      return fromObj(obj);
    }
    return "";
  } catch (e) {
    // Not JSON; treat as plain text
    return body;
  }
}

const prompts = new SharedArray("prompts", () => {
  const path = __ENV.K6_PROMPTS_PATH || "/bench/prompts.json";
  return JSON.parse(open(path));
});

function fnv1a32(str) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    hash ^= str.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
    hash >>>= 0;
  }
  return hash >>> 0;
}

function xorshift32(state) {
  let x = state >>> 0;
  x ^= (x << 13) >>> 0;
  x ^= x >>> 17;
  x ^= (x << 5) >>> 0;
  return x >>> 0;
}

function buildPermutation(n, seedU32) {
  const perm = new Array(n);
  for (let i = 0; i < n; i++) perm[i] = i;
  let state = seedU32 >>> 0;
  if (state === 0) state = 1;
  for (let i = n - 1; i > 0; i--) {
    state = xorshift32(state);
    const j = state % (i + 1);
    const tmp = perm[i];
    perm[i] = perm[j];
    perm[j] = tmp;
  }
  return perm;
}

if (!prompts || prompts.length === 0) {
  throw new Error("prompts is empty; check K6_PROMPTS_PATH");
}

const promptBaseSeed = __ENV.PROMPT_BASE_SEED || "0";
const promptRep = __ENV.PROMPT_REP || "0";
const orderSeedMaterial = `${promptBaseSeed}:${promptRep}:prompt-order:v1`;
const orderSeedU32 = fnv1a32(orderSeedMaterial);
const perm = buildPermutation(prompts.length, orderSeedU32);
const promptIds = prompts.map((p) =>
  p && typeof p === "object" && !Array.isArray(p) ? p.id || null : null,
);

function uniquePromptIdValues(ids) {
  return Array.from(
    new Set(
      ids
        .map((v) => (v === null || v === undefined ? "" : String(v).trim()))
        .filter((v) => v.length > 0),
    ),
  );
}

function buildPromptMetricThresholds(ids) {
  const out = {};
  for (const pid of uniquePromptIdValues(ids)) {
    out[`attempts_measure_prompt{prompt_id:${pid}}`] = ["count>=0"];
    out[`successes_measure_prompt{prompt_id:${pid}}`] = ["count>=0"];
    out[`timeouts_measure_prompt{prompt_id:${pid}}`] = ["count>=0"];
    out[`errors_non_timeout_measure_prompt{prompt_id:${pid}}`] = ["count>=0"];
  }
  return out;
}

function parseMetricTags(key) {
  if (typeof key !== "string" || !key.includes("{") || !key.endsWith("}")) return {};
  const inner = key.split("{", 2)[1].slice(0, -1);
  const tags = {};
  for (const part of inner.split(",")) {
    const item = part.trim();
    if (!item || !item.includes(":")) continue;
    const idx = item.indexOf(":");
    const k = item.slice(0, idx).trim();
    const v = item.slice(idx + 1).trim();
    if (k) tags[k] = v;
  }
  return tags;
}

function extractTaggedCounterSeries(metrics, base, tagKey) {
  const out = {};
  if (!metrics || typeof metrics !== "object") return out;
  for (const [key, metric] of Object.entries(metrics)) {
    if (!(typeof key === "string" && key.startsWith(`${base}{`) && key.endsWith("}"))) continue;
    const tags = parseMetricTags(key);
    const tagValue = tags[tagKey];
    if (!tagValue) continue;
    const values = metric && typeof metric === "object" && metric.values && typeof metric.values === "object" ? metric.values : metric;
    const count = values && typeof values.count === "number" ? values.count : null;
    if (count === null) continue;
    out[String(tagValue)] = count;
  }
  return out;
}

const endpoint = __ENV.N8N_WEBHOOK_URL || "http://n8n:5678/webhook/rag-query";
const inputField = __ENV.N8N_INPUT_FIELD || "chatInput";
const sessionField = __ENV.N8N_SESSION_FIELD || "sessionId";

const authHeader = __ENV.N8N_AUTH_HEADER || "";
const authValue = __ENV.N8N_AUTH_VALUE || "";
const timeout = __ENV.K6_HTTP_TIMEOUT || "120s";

const promptSet = __ENV.BENCH_PROMPT_SET || "in_scope";
const requireCitations =
  (__ENV.K6_REQUIRE_CITATIONS || "0") === "1" && promptSet === "in_scope";

const promptMetricThresholds = buildPromptMetricThresholds(promptIds);

const arrivalRate = __ENV.K6_ARR_RATE ? parseInt(__ENV.K6_ARR_RATE, 10) : null;
const useArrivalRate = arrivalRate !== null && !Number.isNaN(arrivalRate) && arrivalRate > 0;
if (!useArrivalRate) {
  throw new Error("Frontier-only script requires K6_ARR_RATE > 0 (constant-arrival-rate mode)");
}
const arrivalTimeUnit = __ENV.K6_ARR_TIME_UNIT || "1m";
const settleSecondsRaw = parseInt(__ENV.K6_SETTLE_SECONDS || "180", 10);
const measureSecondsRaw = parseInt(__ENV.K6_MEASURE_SECONDS || "720", 10);
const settleSeconds =
  !Number.isNaN(settleSecondsRaw) && settleSecondsRaw >= 0
    ? settleSecondsRaw
    : 180;
const measureSeconds =
  !Number.isNaN(measureSecondsRaw) && measureSecondsRaw > 0
    ? measureSecondsRaw
    : 720;
const arrivalPreAllocatedVUs = parseInt(
  __ENV.K6_ARR_PREALLOCATED_VUS || "20",
  10,
);
const arrivalMaxVUs = parseInt(__ENV.K6_ARR_MAX_VUS || "80", 10);

let promptScheduler = String(__ENV.K6_PROMPT_SCHEDULER || "arrival_global").trim();
if (promptScheduler !== "arrival_global") {
  console.warn(
    `Frontier-only script enforces K6_PROMPT_SCHEDULER=arrival_global (got ${promptScheduler})`,
  );
  promptScheduler = "arrival_global";
}

export const options = settleSeconds > 0
  ? {
      scenarios: {
        settle: {
          executor: "constant-arrival-rate",
          rate: arrivalRate,
          timeUnit: arrivalTimeUnit,
          duration: `${settleSeconds}s`,
          preAllocatedVUs: arrivalPreAllocatedVUs,
          maxVUs: arrivalMaxVUs,
          gracefulStop: "0s",
        },
        measure: {
          executor: "constant-arrival-rate",
          rate: arrivalRate,
          timeUnit: arrivalTimeUnit,
          startTime: `${settleSeconds}s`,
          duration: `${measureSeconds}s`,
          preAllocatedVUs: arrivalPreAllocatedVUs,
          maxVUs: arrivalMaxVUs,
          gracefulStop: "0s",
        },
      },
      summaryTrendStats: ["avg", "min", "med", "max", "p(90)", "p(95)"],
      thresholds: promptMetricThresholds,
    }
  : {
      scenarios: {
        measure: {
          executor: "constant-arrival-rate",
          rate: arrivalRate,
          timeUnit: arrivalTimeUnit,
          duration: `${measureSeconds}s`,
          preAllocatedVUs: arrivalPreAllocatedVUs,
          maxVUs: arrivalMaxVUs,
          gracefulStop: "0s",
        },
      },
      summaryTrendStats: ["avg", "min", "med", "max", "p(90)", "p(95)"],
      thresholds: promptMetricThresholds,
    };

function isTimeout(res) {
  if (!res) return false;
  if (res.status === 408 || res.status === 504) return true;
  if (res.status !== 0) return false;

  const ec = res.error_code;
  if (typeof ec === "number") {
    // k6 uses numeric internal error codes; treat common timeout-ish codes as timeouts.
    if (ec === 1050 || ec === 1051 || ec === 1052) return true;
  }

  const e1 = String(res.error || "").toLowerCase();
  const e2 = String(res.error_code || "").toLowerCase();
  return e1.includes("timeout") || e2.includes("timeout");
}

function promptIdTagFrom(prompt) {
  if (prompt && typeof prompt === "object" && !Array.isArray(prompt)) {
    const id = prompt.id;
    if (id !== undefined && id !== null) {
      const s = String(id);
      return s.length > 0 ? s : "unknown";
    }
  }
  return "unknown";
}

export default function () {
  const inMeasureWindow = useArrivalRate && exec.scenario && exec.scenario.name === "measure";
  const scenarioName = exec.scenario && exec.scenario.name ? exec.scenario.name : "default";
  const iterationInTest =
    exec.scenario && typeof exec.scenario.iterationInTest === "number"
      ? exec.scenario.iterationInTest
      : __ITER;

  const runId = __ENV.BENCH_RUN_ID || "run";
  const rawIndex =
    useArrivalRate && promptScheduler === "arrival_global"
      ? iterationInTest % prompts.length
      : (__ITER + (__VU - 1)) % prompts.length;
  const promptIndex = perm[rawIndex];
  const prompt = prompts[promptIndex];
  const promptId = typeof prompt === "string" ? null : prompt.id;
  const promptText = typeof prompt === "string" ? prompt : prompt.text;
  const promptIdTag = promptIdTagFrom(prompt);
  const promptTags = { prompt_id: promptIdTag };
  const payload = JSON.stringify({
    [inputField]: promptText,
    [sessionField]: useArrivalRate
      ? `k6-n8n-${runId}-${scenarioName}-${iterationInTest}`
      : `k6-n8n-${runId}-${__VU}-${__ITER}`,
    prompt_id: promptId,
    request_meta: {
      vu: __VU,
      iter: __ITER,
      run_id: runId,
      prompt_index: promptIndex,
      prompt_index_raw: rawIndex,
      prompt_scheduler: promptScheduler,
      scenario: scenarioName,
      iteration_in_test: iterationInTest,
    },
  });

  const headers = {
    "Content-Type": "application/json",
  };
  if (authHeader && authValue) {
    headers[authHeader] = authValue;
  }

  const res = http.post(endpoint, payload, { headers, timeout });
  resp_body_bytes.add(res.body ? res.body.length : 0);
  let contractOk = false;
  let jsonParseFail = false;
  const bodyText = res && typeof res.body === "string" ? res.body : "";
  try {
    const obj = bodyText && bodyText.trim().length > 0 ? JSON.parse(bodyText) : null;
    if (Array.isArray(obj) && obj.length > 0) {
      // Accept either a direct {output: string} item or the common {json: {output: string}} envelope.
      contractOk = obj.some((it) => {
        if (!it || typeof it !== "object" || Array.isArray(it)) return false;
        if (typeof it.output === "string" && it.output.length >= 0) return true;
        if (
          it.json &&
          typeof it.json === "object" &&
          !Array.isArray(it.json) &&
          typeof it.json.output === "string" &&
          it.json.output.length >= 0
        )
          return true;
        return false;
      });
    }
  } catch (e) {
    contractOk = false;
    jsonParseFail = bodyText && bodyText.trim().length > 0;
  }
  const answer = extractAnswer(res.body);
  answer_chars.add(answer ? String(answer).length : 0);
  const hasCitation = String(answer || "").includes("[source:");

  const success =
    res.status === 200 &&
    contractOk &&
    String(answer || "").trim().length > 0 &&
    (!requireCitations || hasCitation);
  const timeoutAttempt = isTimeout(res);

  check(res, {
    "status is 200": (r) => r.status === 200,
    "contract: json output[]": () => contractOk,
    "answer non-empty": () => (String(answer || "").trim().length > 0),
    "citation present": () => !requireCitations || hasCitation,
  });

  if (inMeasureWindow) {
    attempts_measure.add(1);
    attempts_measure_prompt.add(1, promptTags);
    if (res.status === 429) http_429_measure.add(1);
    if (res.status !== 200) http_non_200_measure.add(1);
    if (res.status >= 500 && res.status <= 599) http_5xx_measure.add(1);
    if (timeoutAttempt) {
      timeouts_measure.add(1);
      timeouts_measure_prompt.add(1, promptTags);
    }
    if (res.status === 0 && !timeoutAttempt) {
      transport_error_non_timeout_measure.add(1);
    }

    if (success) {
      successes_measure.add(1);
      successes_measure_prompt.add(1, promptTags);
      // Extract token usage from response headers for correlation analysis
      const tokenPrompt = res.headers && res.headers["X-Token-Prompt"] ? parseInt(res.headers["X-Token-Prompt"], 10) : null;
      const tokenCompletion = res.headers && res.headers["X-Token-Completion"] ? parseInt(res.headers["X-Token-Completion"], 10) : null;
      const tokenTotal = res.headers && res.headers["X-Token-Total"] ? parseInt(res.headers["X-Token-Total"], 10) : null;
      if (tokenPrompt !== null && !isNaN(tokenPrompt)) tokens_prompt.add(tokenPrompt);
      if (tokenCompletion !== null && !isNaN(tokenCompletion)) tokens_completion.add(tokenCompletion);
      if (tokenTotal !== null && !isNaN(tokenTotal)) tokens_total.add(tokenTotal);
      const d = res.timings && typeof res.timings.duration === "number" ? res.timings.duration : 0;
      latency_measure_ms.add(d);
    } else {
      errors_total_measure.add(1);
      if (!timeoutAttempt) {
        errors_non_timeout_measure.add(1);
        errors_non_timeout_measure_prompt.add(1, promptTags);
      }

      // Failure taxonomy (measure only; totals are untagged).
      if (jsonParseFail) {
        json_parse_fail_measure.add(1);
      } else if (res.status === 200 && !contractOk) {
        contract_fail_measure.add(1);
      } else if (res.status === 200 && contractOk) {
        if (String(answer || "").trim().length === 0) {
          empty_answer_measure.add(1);
        } else if (requireCitations && !hasCitation) {
          citation_missing_measure.add(1);
        }
      }
    }
  }

  // Frontier-only: open-loop arrival mode, no closed-loop pacing sleep.
}

export function handleSummary(data) {
  const runId = __ENV.BENCH_RUN_ID || "run";
  const artifactDir = __ENV.K6_ARTIFACT_DIR || ".";
  const outPath = `${artifactDir}/prompt_order_${runId}.json`;
  const promptMetricsPath = `${artifactDir}/prompt_metrics_${runId}.json`;
  const payload = {
    base_seed: promptBaseSeed,
    rep: promptRep,
    order_seed_u32: orderSeedU32,
    prompts_length: prompts.length,
    prompt_ids: promptIds,
    permutation_indices: perm,
    permutation_prompt_ids: perm.map((i) => promptIds[i]),
  };
  const metrics = data && typeof data === "object" ? data.metrics || {} : {};
  const promptMetrics = {
    run_id: runId,
    prompt_ids: uniquePromptIdValues(promptIds),
    attempts_by_prompt: extractTaggedCounterSeries(metrics, "attempts_measure_prompt", "prompt_id"),
    successes_by_prompt: extractTaggedCounterSeries(metrics, "successes_measure_prompt", "prompt_id"),
    timeouts_by_prompt: extractTaggedCounterSeries(metrics, "timeouts_measure_prompt", "prompt_id"),
    errors_non_timeout_by_prompt: extractTaggedCounterSeries(metrics, "errors_non_timeout_measure_prompt", "prompt_id"),
  };
  return {
    [outPath]: JSON.stringify(payload, null, 2),
    [promptMetricsPath]: JSON.stringify(promptMetrics, null, 2),
  };
}
