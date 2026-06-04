/* Xodexa AI Benchmark — curated catalog of current top-brand models for the run picker.
 *
 * VERIFIED from each provider's own docs/sources in June 2026. Model identifiers are the
 * exact API strings. For non-OpenAI/Anthropic brands the platform reaches them through an
 * OpenAI-compatible endpoint, so each group carries the provider's OpenAI-compatible
 * base_url (pre-filled, editable). Names + endpoints change over time — the run form lets
 * the user edit anything, and the server validates the model against the provider.
 *
 * Sources: platform.openai.com/developers docs · platform.claude.com/docs ·
 * ai.google.dev/gemini-api/docs/models · docs.x.ai · api-docs.deepseek.com ·
 * llama.developer.meta.com · docs.mistral.ai · Alibaba Model Studio (DashScope) ·
 * platform.moonshot.ai · z.ai/Zhipu · docs.cohere.com.
 */
window.XODEXA_MODELS = {
  verified: "June 2026",
  brands: [
    // ── Native providers (no base_url required) ──────────────────────────────

    { brand: "OpenAI", provider: "openai", base_url: "",
      models: ["gpt-5.5-pro", "gpt-5.5", "gpt-5.4-pro", "gpt-5.4",
               "gpt-5.4-mini", "gpt-5.4-nano",
               "gpt-4.1", "gpt-4.1-mini"] },

    { brand: "Anthropic (Claude)", provider: "anthropic", base_url: "",
      models: ["claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
               "claude-sonnet-4-6", "claude-haiku-4-5"] },

    // ── OpenAI-compatible providers (base_url pre-filled) ────────────────────

    { brand: "Google (Gemini)", provider: "openai-compatible",
      base_url: "https://generativelanguage.googleapis.com/v1beta/openai/",
      models: ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
               "gemini-2.0-flash", "gemini-1.5-pro"] },

    { brand: "xAI (Grok)", provider: "openai-compatible",
      base_url: "https://api.x.ai/v1",
      models: ["grok-4.3"] },

    { brand: "DeepSeek", provider: "openai-compatible",
      base_url: "https://api.deepseek.com",
      models: ["deepseek-v4-pro", "deepseek-v4-flash"] },

    { brand: "Meta (Llama)", provider: "openai-compatible",
      base_url: "https://api.llama.com/compat/v1/",
      models: ["Llama-4-Maverick-17B-128E-Instruct",
               "Llama-4-Scout-17B-16E-Instruct"] },

    { brand: "Mistral AI", provider: "openai-compatible",
      base_url: "https://api.mistral.ai/v1",
      models: ["mistral-large-latest", "mistral-large-2512",
               "mistral-medium-latest", "mistral-small-latest"] },

    { brand: "Alibaba (Qwen)", provider: "openai-compatible",
      base_url: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
      models: ["qwen3-max", "qwen3.5-flash", "qwen-plus"] },

    { brand: "Moonshot AI (Kimi)", provider: "openai-compatible",
      base_url: "https://api.moonshot.ai/v1",
      models: ["kimi-k2.6", "kimi-k2.5"] },

    { brand: "Zhipu / Z.ai (GLM)", provider: "openai-compatible",
      base_url: "https://api.z.ai/api/paas/v4",
      models: ["glm-5.1", "glm-5", "glm-4.7"] },

    { brand: "Cohere (Command)", provider: "openai-compatible",
      base_url: "https://api.cohere.ai/compatibility/v1",
      models: ["command-a-plus-05-2026", "command-a-03-2025"] },
  ],
};
