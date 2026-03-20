import type { ZoScenario } from "./types.js";

type ScenarioModelConfig = {
  modelName: string;
  label: string;
};

function scenarioEnvKey(scenario: ZoScenario) {
  return `ZO_MODEL_${scenario.replaceAll("-", "_").toUpperCase()}`;
}

export function getScenarioModelConfig(
  scenario: ZoScenario,
  env: NodeJS.ProcessEnv = process.env,
): ScenarioModelConfig {
  const rawMap = env.ZO_MODEL_SCENARIO_MAP_JSON;
  if (rawMap) {
    const parsed = JSON.parse(rawMap) as Record<string, string | ScenarioModelConfig>;
    const entry = parsed[scenario];
    if (typeof entry === "string" && entry.trim()) {
      return { modelName: entry, label: entry };
    }
    if (entry && typeof entry === "object" && entry.modelName) {
      return { modelName: entry.modelName, label: entry.label || entry.modelName };
    }
  }

  const envValue = env[scenarioEnvKey(scenario)]?.trim();
  if (envValue) {
    return { modelName: envValue, label: envValue };
  }

  const fallback = env.ZO_DEFAULT_MODEL_NAME?.trim();
  if (fallback) {
    return { modelName: fallback, label: fallback };
  }

  throw new Error(`No Zo model configured for scenario '${scenario}'`);
}

