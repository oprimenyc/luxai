export const SUPPORTED_MODELS = {
  openai: {
    "gpt-4o": { contextWindow: 128_000, maxOutput: 16_384 },
    "gpt-4o-mini": { contextWindow: 128_000, maxOutput: 16_384 },
    "gpt-4-turbo": { contextWindow: 128_000, maxOutput: 4_096 },
    o1: { contextWindow: 200_000, maxOutput: 100_000 },
    "o1-mini": { contextWindow: 128_000, maxOutput: 65_536 },
  },
  anthropic: {
    "claude-3-5-sonnet-20241022": { contextWindow: 200_000, maxOutput: 8_192 },
    "claude-3-5-haiku-20241022": { contextWindow: 200_000, maxOutput: 8_192 },
    "claude-3-opus-20240229": { contextWindow: 200_000, maxOutput: 4_096 },
  },
} as const;

export type OpenAIModel = keyof typeof SUPPORTED_MODELS.openai;
export type AnthropicModel = keyof typeof SUPPORTED_MODELS.anthropic;
export type SupportedModel = OpenAIModel | AnthropicModel;

export function isOpenAIModel(model: string): model is OpenAIModel {
  return model in SUPPORTED_MODELS.openai;
}

export function isAnthropicModel(model: string): model is AnthropicModel {
  return model in SUPPORTED_MODELS.anthropic;
}

export function getModelInfo(model: SupportedModel) {
  if (isOpenAIModel(model)) return SUPPORTED_MODELS.openai[model];
  if (isAnthropicModel(model)) return SUPPORTED_MODELS.anthropic[model];
  throw new Error(`Unknown model: ${model}`);
}
