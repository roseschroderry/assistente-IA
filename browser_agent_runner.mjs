const rawPayload = process.argv[2] || "{}";

function done(payload) {
  process.stdout.write(JSON.stringify(payload));
}

async function main() {
  const payload = JSON.parse(rawPayload);
  let Stagehand;
  try {
    ({ Stagehand } = await import("@browserbasehq/stagehand"));
  } catch (error) {
    done({
      status: "error",
      provider: "browserbase-stagehand",
      error: "Pacote @browserbasehq/stagehand nao instalado.",
      detail: String(error && error.message ? error.message : error),
    });
    return;
  }

  const stagehand = new Stagehand({
    env: process.env.BROWSERBASE_API_KEY ? "BROWSERBASE" : "LOCAL",
    apiKey: process.env.BROWSERBASE_API_KEY,
    projectId: process.env.BROWSERBASE_PROJECT_ID,
    model: process.env.STAGEHAND_MODEL || process.env.OPENROUTER_MODEL || "openai/gpt-4o-mini",
    verbose: Number(process.env.STAGEHAND_VERBOSE || 0),
  });

  try {
    await stagehand.init();
    if (payload.url) {
      await stagehand.page.goto(payload.url, { waitUntil: "domcontentloaded" });
    }

    let result;
    if (payload.mode === "read") {
      result = await stagehand.extract(payload.instruction || "extraia um resumo da pagina");
    } else {
      result = await stagehand.act(payload.instruction);
    }

    done({
      status: "completed",
      provider: "browserbase-stagehand",
      result,
      url: stagehand.page?.url?.() || payload.url || "",
    });
  } catch (error) {
    done({
      status: "error",
      provider: "browserbase-stagehand",
      error: String(error && error.message ? error.message : error),
    });
  } finally {
    try {
      await stagehand.close();
    } catch {}
  }
}

main().catch((error) => {
  done({
    status: "error",
    provider: "browserbase-stagehand",
    error: String(error && error.message ? error.message : error),
  });
});
