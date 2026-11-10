"""Generates workflow/creative-brief-intake.json. Edit here, re-run, re-import."""
import json, uuid
from pathlib import Path

def nid(): return str(uuid.uuid4())

def cond(left, op_type, op, right=None, single=False):
    c = {"id": nid(), "leftValue": left, "operator": {"type": op_type, "operation": op}}
    if single: c["operator"]["singleValue"] = True
    else: c["rightValue"] = right
    return c

def if_params(*conds):
    return {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                           "conditions": list(conds), "combinator": "and"},
            "looseTypeValidation": True, "options": {}}

RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000}

NORMALIZE = r"""
// One place to change endpoints and the model.
const CONFIG = {
  llm_url: 'http://127.0.0.1:11434/api/chat',      // Ollama native chat API (local, no key)
  model: '__MODEL__',
  sheets_url: 'http://127.0.0.1:8099/sheets/append', // mock Google Sheets
  slack_url: 'http://127.0.0.1:8099/slack/webhook',  // mock Slack incoming webhook
  high_priority_score: 70,
  parse_schema: __PARSE_SCHEMA__,
  parse_system: __PARSE_SYSTEM__,
  concept_schema: __GEN_SCHEMA__,
  concept_system: __GEN_SYSTEM__,
};

const body = $input.first().json.body ?? {};
const clean = (v) => (typeof v === 'string' ? v.trim() : v);
const lead = {
  name: clean(body.name) || '',
  email: (clean(body.email) || '').toLowerCase(),
  company: clean(body.company) || '',
  website: clean(body.website) || '',
  brief: clean(body.brief) || '',
  source: clean(body.source) || 'website-form',
};

const errors = [];
if (!lead.company) errors.push('company is required');
if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(lead.email)) errors.push('a valid email is required');
if (lead.brief.length < 20) errors.push('brief must be at least 20 characters');
if (lead.brief.length > 4000) errors.push('brief must be under 4000 characters');

const brief_id = 'BR-' + new Date().toISOString().slice(0, 10).replace(/-/g, '') + '-' +
  Math.random().toString(36).slice(2, 7).toUpperCase();

return [{ json: { ...lead, brief_id, received_at: new Date().toISOString(), valid: errors.length === 0, errors, config: CONFIG } }];
"""

PARSE_SCHEMA = {
  "type": "object",
  "properties": {
    "product": {"type": "string"},
    "industry": {"type": "string"},
    "goal": {"type": "string", "enum": ["sales", "leads", "app_installs", "awareness", "engagement", "unclear"]},
    "audience": {"type": "string"},
    "platforms": {"type": "array", "items": {"type": "string"}},
    "formats": {"type": "array", "items": {"type": "string", "enum": ["ugc_video", "ai_avatar_video", "static_ad", "carousel", "product_photo"]}},
    "deliverable_count": {"type": ["integer", "null"]},
    "budget_usd": {"type": ["number", "null"]},
    "deadline": {"type": ["string", "null"]},
    "tone": {"type": "string"},
    "summary": {"type": "string"},
  },
  "required": ["product", "industry", "goal", "audience", "platforms", "formats", "deliverable_count", "budget_usd", "deadline", "tone", "summary"],
}

PARSE_SYSTEM = ("You are a creative-ops assistant at an AI ad agency. Extract a structured creative spec from a client brief. "
  "Only use facts stated in the brief. If a field is not stated, use null (or an empty list / 'unclear'). "
  "Convert budgets to US dollars only if the brief gives dollars; otherwise null. Return JSON only.")

PARSE_BODY = "={{ JSON.stringify({ model: $json.config.model, stream: false, think: false, options: { temperature: 0, num_predict: 400 }, format: $json.config.parse_schema, messages: [ { role: 'system', content: $json.config.parse_system }, { role: 'user', content: 'Company: ' + $json.company + '\\nWebsite: ' + $json.website + '\\nBrief: ' + $json.brief } ] }) }}"

VALIDATE = r"""
// The model extracts; code decides. Scoring and routing never depend on the model's opinion.
const lead = $('Normalize & validate').first().json;
const res = $input.first().json;
let spec;
try {
  spec = JSON.parse(res.message?.content ?? '');
} catch (e) {
  throw new Error(`LLM returned non-JSON for ${lead.brief_id}: ${String(res.message?.content).slice(0, 200)}`);
}

// Ground every list in the brief text: small models happily invent "email marketing" or "carousels".
const text = lead.brief.toLowerCase();
const FORMAT_EVIDENCE = {
  ugc_video: /ugc|creator|testimonial|unboxing/,
  ai_avatar_video: /avatar|talking[- ]head|spokesperson|presenter/,
  static_ad: /static|image ad|banner|still/,
  carousel: /carousel/,
  product_photo: /product (photo|shot|image)|catalog|catalogue|packshot/,
};
const PLATFORM_EVIDENCE = { Meta: /meta|facebook|instagram|reels/, TikTok: /tiktok/, YouTube: /youtube|shorts/,
  Google: /google ads|google display|pmax|performance max/, LinkedIn: /linkedin/, Pinterest: /pinterest/ };
const llmFormats = Array.isArray(spec.formats) ? spec.formats : [];
spec.formats = Object.keys(FORMAT_EVIDENCE).filter((f) => FORMAT_EVIDENCE[f].test(text));
// "video" alone is ambiguous: accept the model's video pick only when the brief says video.
if (/video/.test(text) && !spec.formats.some((f) => f.endsWith('video'))) {
  const v = llmFormats.find((f) => f.endsWith('video'));
  if (v) spec.formats.unshift(v);
}
spec.platforms = Object.keys(PLATFORM_EVIDENCE).filter((p) => PLATFORM_EVIDENCE[p].test(text));
const num = (v) => (typeof v === 'number' && isFinite(v) && v > 0 ? v : null);
spec.budget_usd = num(spec.budget_usd);
spec.deliverable_count = num(spec.deliverable_count);
if (spec.budget_usd && !/\$|usd|dollar/.test(text)) spec.budget_usd = null;
if (spec.deadline && !/\d|week|month|asap|launch|end of/.test(text)) spec.deadline = null;
if (spec.deliverable_count && !new RegExp(`\\b${spec.deliverable_count}\\b`).test(text)) spec.deliverable_count = null;
if (spec.audience && !/women|men|parents|moms|dads|gen z|millennial|students|\d{2}\s*[-–]\s*\d{2}|aged|owners|teams|buyers|customers who/.test(text)) spec.audience = 'unclear';

const missing = [];
if (!spec.formats.length) missing.push('formats');
if (!spec.platforms.length) missing.push('platforms');
if (!spec.audience || spec.audience.toLowerCase() === 'unclear') missing.push('audience');
if (!spec.budget_usd) missing.push('budget');
if (!spec.deadline) missing.push('deadline');
if (!spec.deliverable_count) missing.push('deliverable_count');

const completeness = Math.round(((6 - missing.length) / 6) * 100);
let score = completeness * 0.5;
if (spec.budget_usd >= 5000) score += 30; else if (spec.budget_usd >= 1500) score += 20; else if (spec.budget_usd) score += 10;
if (spec.goal === 'sales' || spec.goal === 'leads' || spec.goal === 'app_installs') score += 10;
if (spec.formats.some((f) => f.includes('video'))) score += 10;
score = Math.min(100, Math.round(score));

const ready = missing.length <= 1 && spec.formats.length > 0;
return [{ json: {
  ...lead, spec, missing, completeness, lead_score: score, ready,
  priority: score >= lead.config.high_priority_score ? 'high' : 'standard',
  usage: { model: res.model, tokens: (res.prompt_eval_count ?? 0) + (res.eval_count ?? 0), seconds: +((res.total_duration ?? 0) / 1e9).toFixed(1) },
} }];
"""

GEN_SCHEMA = {
  "type": "object",
  "properties": {
    "concepts": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "object", "properties": {
      "hook": {"type": "string"}, "visual": {"type": "string"}}, "required": ["hook", "visual"]}},
    "opening_line": {"type": "string"},
  },
  "required": ["concepts", "opening_line"],
}
GEN_SYSTEM = ("You are a copywriter at an AI ad agency. Given a creative spec, return three distinct ad concepts. "
  "Each has a 'hook' (the first line a viewer reads or hears, under 12 words) and a 'visual' (one sentence describing the scene: "
  "subject, setting, lighting, camera). Also return 'opening_line': one friendly sentence to the client that reflects their product "
  "and audience. No numbers, prices or dates anywhere. Return JSON only.")
GEN_BODY = "={{ JSON.stringify({ model: $json.config.model, stream: false, think: false, options: { temperature: 0.4, num_predict: 700 }, format: $json.config.concept_schema, messages: [ { role: 'system', content: $json.config.concept_system }, { role: 'user', content: 'Client: ' + $json.name + ' at ' + $json.company + '\\nSpec: ' + JSON.stringify($json.spec) } ] }) }}"

COMBINE_READY = r"""
// The model supplies creative ideas; the facts in the email come from the validated spec.
const b = $('Validate & score').first().json;
const res = $input.first().json;
let out;
try { out = JSON.parse(res.message?.content ?? ''); }
catch (e) { throw new Error(`Concept LLM returned non-JSON for ${b.brief_id}`); }
const raw = (out.concepts ?? []).filter((c) => c && c.hook && c.visual).slice(0, 3);
if (raw.length < 2) throw new Error(`Concept LLM returned ${raw.length} usable concepts for ${b.brief_id}`);

const LABEL = { ugc_video: 'UGC-style video', ai_avatar_video: 'AI avatar video', static_ad: 'static ad', carousel: 'carousel', product_photo: 'product photo' };
const ASPECT = { Meta: '4:5', TikTok: '9:16', YouTube: '9:16', Google: '1:1', LinkedIn: '1:1', Pinterest: '2:3' };
const aspect = ASPECT[b.spec.platforms[0]] ?? '4:5';
const concepts = raw.map((c, i) => {
  const format = b.spec.formats[i % b.spec.formats.length];
  const video = format.endsWith('video');
  const visual = c.visual.replace(/\s+/g, ' ').trim().replace(/\.$/, '');
  return {
    format, tool: video ? 'Kling' : 'Midjourney', hook: c.hook.trim(),
    prompt: video
      ? `${visual}. Handheld smartphone look, natural light, ${b.spec.tone || 'authentic'} mood, 5 seconds, ${aspect}.`
      : `${visual}, ${b.spec.tone || 'clean'} styling, soft natural light, ad-ready composition --ar ${aspect} --style raw`,
  };
});

const strip = (s) => (/\d|\$/.test(s ?? '') ? '' : (s ?? '').trim());
const first = (b.name || '').split(' ')[0] || 'there';
const fmt = b.spec.formats.map((f) => LABEL[f]).join(' and ');
const lines = [`Hi ${first},`, '',
  [strip(out.opening_line), `Thanks for the ${b.company} brief.`].filter(Boolean).join(' '), '',
  'Here is what we have:',
  `- Goal: ${b.spec.goal}`, `- Audience: ${b.spec.audience}`, `- Formats: ${fmt}`,
  `- Platforms: ${b.spec.platforms.join(', ')}`,
  ...(b.spec.deliverable_count ? [`- Volume: ${b.spec.deliverable_count} per format`] : []),
  ...(b.spec.deadline ? [`- Live by: ${b.spec.deadline}`] : []), '',
  `First concept direction: "${concepts[0].hook}"`, '',
  'Does a 30-minute brief call this week work? Pick any slot and we will bring a creative spec and first variations.', '',
  'The Kreative Media team'];
return [{ json: { ...b, status: 'ready_for_call', concepts,
  reply: { to: b.email, subject: `${b.company} brief: next step`, body: lines.join('\n') },
  usage: { model: b.usage.model, tokens: b.usage.tokens + (res.prompt_eval_count ?? 0) + (res.eval_count ?? 0),
           seconds: +(b.usage.seconds + (res.total_duration ?? 0) / 1e9).toFixed(1) } } }];
"""

CLARIFY = r"""
// Incomplete briefs get a templated reply: no second LLM call, so no extra cost or risk.
const b = $input.first().json;
const Q = {
  formats: 'Which formats do you need: UGC-style video, AI avatar video, static ads, carousels or product photos?',
  platforms: 'Where will the ads run (Meta, TikTok, YouTube Shorts, Google)?',
  audience: 'Who is the target customer?',
  budget: 'What budget range do you have in mind for this round?',
  deadline: 'When do you need the first creatives live?',
  deliverable_count: 'Roughly how many final creatives do you want?',
};
const first = (b.name || '').split(' ')[0] || 'there';
const body = [`Hi ${first},`, '',
  `Thanks for sending the brief for ${b.company}. Before we book the brief call, a few quick questions:`, '',
  ...b.missing.map((m, i) => `${i + 1}. ${Q[m]}`), '',
  'Reply here and we will send a creative spec the same day.', '', 'The Kreative Media team'].join('\n');
return [{ json: { ...b, status: 'needs_info', concepts: [],
  reply: { to: b.email, subject: `A few questions about the ${b.company} brief`, body } } }];
"""

BUILD_ROW = r"""
const b = $input.first().json;
return [{ json: { ...b, row: {
  received_at: b.received_at, brief_id: b.brief_id, brand: b.company, contact_email: b.email, status: b.status,
  completeness: b.completeness, lead_score: b.lead_score, priority: b.priority, formats: b.spec.formats.join(', '),
  missing_fields: b.missing.join(', '), prompt_count: b.concepts.length, reply_subject: b.reply.subject,
  model: b.usage.model, tokens_used: b.usage.tokens, llm_seconds: b.usage.seconds,
} } }];
"""

FORMAT_ERROR = r"""
// Reached when an LLM call fails after 3 tries, or its output fails validation.
const lead = $('Normalize & validate').first().json;
const err = $input.first().json.error ?? $input.first().json;
const message = typeof err === 'string' ? err : (err.message || JSON.stringify(err)).slice(0, 300);
return [{ json: { brief_id: lead.brief_id, company: lead.company, failed_at: new Date().toISOString(), message,
  slack: { text: `:rotating_light: Brief ${lead.brief_id} (${lead.company}) failed in n8n: ${message}. Lead is safe in the execution log; reply manually.` },
  config: lead.config } }];
"""

import os
NORMALIZE = NORMALIZE.replace("__MODEL__", os.environ.get("LLM_MODEL", "qwen3:0.6b"))
NORMALIZE = (NORMALIZE.replace("__PARSE_SCHEMA__", json.dumps(PARSE_SCHEMA)).replace("__PARSE_SYSTEM__", json.dumps(PARSE_SYSTEM))
             .replace("__GEN_SCHEMA__", json.dumps(GEN_SCHEMA)).replace("__GEN_SYSTEM__", json.dumps(GEN_SYSTEM)))
nodes, conns = [], {}
def node(name, typ, ver, params, pos, **extra):
    n = {"id": nid(), "name": name, "type": typ, "typeVersion": ver, "position": pos, "parameters": params}
    n.update(extra); nodes.append(n); return name
def link(a, b, out=0):
    conns.setdefault(a, {"main": []})
    while len(conns[a]["main"]) <= out: conns[a]["main"].append([])
    conns[a]["main"][out].append({"node": b, "type": "main", "index": 0})

def http(name, url_expr, body_expr, pos, error_out=True):
    extra = dict(RETRY)
    if error_out: extra["onError"] = "continueErrorOutput"
    return node(name, "n8n-nodes-base.httpRequest", 4.2, {
        "method": "POST", "url": url_expr, "sendBody": True, "specifyBody": "json", "jsonBody": body_expr,
        "options": {"timeout": 180000}}, pos, **extra)

def code(name, js, pos, **extra):
    return node(name, "n8n-nodes-base.code", 2, {"jsCode": js.strip()}, pos, **extra)

def respond(name, code_, body, pos):
    return node(name, "n8n-nodes-base.respondToWebhook", 1.1, {"respondWith": "json", "responseBody": body,
        "options": {"responseCode": code_}}, pos)

node("Brief webhook", "n8n-nodes-base.webhook", 2, {"httpMethod": "POST", "path": "creative-brief",
     "responseMode": "responseNode", "options": {}}, [0, 300], webhookId=nid())
code("Normalize & validate", NORMALIZE, [220, 300])
node("Valid payload?", "n8n-nodes-base.if", 2.2, if_params(cond("={{ $json.valid }}", "boolean", "true", single=True)), [440, 300])
respond("Respond 400", 400, "={{ { ok: false, errors: $json.errors } }}", [660, 520])
http("LLM: parse brief", "={{ $json.config.llm_url }}", PARSE_BODY, [660, 280])
code("Validate & score", VALIDATE, [880, 260], onError="continueErrorOutput")
node("Brief complete?", "n8n-nodes-base.if", 2.2, if_params(cond("={{ $json.ready }}", "boolean", "true", single=True)), [1100, 260])
http("LLM: concepts + reply", "={{ $json.config.llm_url }}", GEN_BODY, [1320, 160])
code("Combine draft", COMBINE_READY, [1540, 140], onError="continueErrorOutput")
code("Clarifying questions", CLARIFY, [1320, 380])
code("Build row", BUILD_ROW, [1760, 260])
node("Append row (Sheets)", "n8n-nodes-base.httpRequest", 4.2, {"method": "POST", "url": "={{ $json.config.sheets_url }}",
     "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json.row) }}", "options": {"timeout": 15000}},
     [1980, 260], **RETRY)
node("High priority?", "n8n-nodes-base.if", 2.2, if_params(cond("={{ $('Build row').item.json.priority }}", "string", "equals", "high")), [2200, 160])
node("Slack: hot lead", "n8n-nodes-base.httpRequest", 4.2, {"method": "POST", "url": "={{ $('Build row').item.json.config.slack_url }}",
     "sendBody": True, "specifyBody": "json",
     "jsonBody": "={{ JSON.stringify({ text: ':fire: ' + $('Build row').item.json.company + ' scored ' + $('Build row').item.json.lead_score + '/100 (' + $('Build row').item.json.spec.formats.join(', ') + '). Draft reply ready: ' + $('Build row').item.json.reply.subject }) }}",
     "options": {"timeout": 15000}}, [2420, 140], **RETRY, onError="continueRegularOutput")
respond("Respond 200", 200, "={{ { ok: true, brief_id: $('Build row').item.json.brief_id, status: $('Build row').item.json.status, lead_score: $('Build row').item.json.lead_score, priority: $('Build row').item.json.priority, missing: $('Build row').item.json.missing, spec: $('Build row').item.json.spec, concepts: $('Build row').item.json.concepts, reply: $('Build row').item.json.reply, usage: $('Build row').item.json.usage } }}", [2200, 380])
code("Format error", FORMAT_ERROR, [1540, 620])
node("Slack: ops alert", "n8n-nodes-base.httpRequest", 4.2, {"method": "POST", "url": "={{ $json.config.slack_url }}",
     "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json.slack) }}", "options": {"timeout": 15000}},
     [1760, 620], **RETRY, onError="continueRegularOutput")
respond("Respond 502", 502, "={{ { ok: false, brief_id: $('Format error').item.json.brief_id, error: 'processing failed; the team has been alerted' } }}", [1980, 620])

link("Brief webhook", "Normalize & validate")
link("Normalize & validate", "Valid payload?")
link("Valid payload?", "LLM: parse brief", 0)
link("Valid payload?", "Respond 400", 1)
link("LLM: parse brief", "Validate & score", 0)
link("LLM: parse brief", "Format error", 1)
link("Validate & score", "Brief complete?", 0)
link("Validate & score", "Format error", 1)
link("Brief complete?", "LLM: concepts + reply", 0)
link("Brief complete?", "Clarifying questions", 1)
link("LLM: concepts + reply", "Combine draft", 0)
link("LLM: concepts + reply", "Format error", 1)
link("Combine draft", "Build row", 0)
link("Combine draft", "Format error", 1)
link("Clarifying questions", "Build row")
link("Build row", "Append row (Sheets)")
link("Append row (Sheets)", "High priority?")
link("Append row (Sheets)", "Respond 200")
link("High priority?", "Slack: hot lead", 0)
link("Format error", "Slack: ops alert")
link("Slack: ops alert", "Respond 502")

wf = {"name": "Creative brief intake (AI)", "nodes": nodes, "connections": conns, "active": False,
      "settings": {"executionOrder": "v1", "saveDataErrorExecution": "all", "saveDataSuccessExecution": "all"},
      "pinData": {}, "id": "kmBriefIntake01", "tags": []}
out = Path(__file__).with_name("creative-brief-intake.json")
out.write_text(json.dumps(wf, indent=2))
print("wrote", out, len(nodes), "nodes")
