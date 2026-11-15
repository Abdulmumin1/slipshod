import { DurableObject } from "cloudflare:workers";

const PORT = 7860;
const SLEEP_AFTER_MS = 15 * 60 * 1000;

const WAKING_PAGE = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>slipshod: waking up</title>
<style>
  body{font:16px/1.5 system-ui,sans-serif;max-width:560px;margin:18vh auto;padding:0 24px;color:#222}
  .bar{height:4px;background:#eee;border-radius:2px;overflow:hidden;margin:24px 0}
  .bar div{height:100%;width:30%;background:#f97316;animation:s 1.2s infinite ease-in-out}
  @keyframes s{0%{margin-left:-30%}100%{margin-left:100%}}
  small{color:#777}
</style></head><body>
<h2>slipshod</h2>
<p>The demo sleeps when nobody is using it. It's starting up, which usually takes 10 to 20 seconds.</p>
<div class="bar"><div></div></div>
<small>This page reloads by itself. Source: <a href="https://github.com/Abdulmumin1/slipshod">github.com/Abdulmumin1/slipshod</a></small>
<script>
  const poll = async () => {
    try { const r = await fetch("/__status", {cache: "no-store"}); if ((await r.json()).ready) return location.reload(); } catch {}
    setTimeout(poll, 1500);
  };
  poll();
</script></body></html>`;

export class SlipshodApp extends DurableObject {
	constructor(ctx, env) {
		super(ctx, env);
		this.ready = false;
		this.version = env.CF_VERSION_METADATA?.id ?? "dev";
		const container = ctx.container;
		if (container?.running) {
			void ctx.blockConcurrencyWhile(async () => {
				// A container started by an older deploy runs the old image: replace it.
				if ((await ctx.storage.get("version")) !== this.version) {
					await container.destroy("superseded by a new deploy");
					return;
				}
				await container.setInactivityTimeout(SLEEP_AFTER_MS);
				this.observeExit();
			});
		}
	}

	ensureStarted() {
		this.starting ??= this.startAndWaitForPort()
			.then(() => { this.ready = true; })
			.finally(() => { this.starting = undefined; });
		return this.starting;
	}

	async fetch(request) {
		const url = new URL(request.url);

		if (url.pathname === "/__status") {
			if (!this.ready) this.ctx.waitUntil(this.ensureStarted().catch(() => {}));
			return Response.json({ ready: this.ready }, { headers: { "cache-control": "no-store" } });
		}

		// Show a friendly page instead of a long spinner while the container boots.
		const wantsPage = request.method === "GET" && (request.headers.get("accept") || "").includes("text/html");
		if (!this.ready && wantsPage) {
			this.ctx.waitUntil(this.ensureStarted().catch((e) => console.error("start failed", e)));
			return new Response(WAKING_PAGE, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
		}

		await this.ensureStarted();
		const target = new URL(url.pathname + url.search, "http://container");
		const forwarded = new Request(target, request);
		forwarded.headers.set("x-forwarded-host", url.host);
		forwarded.headers.set("x-forwarded-proto", url.protocol.replace(":", ""));
		forwarded.headers.delete("host");
		return this.ctx.container.getTcpPort(PORT).fetch(forwarded);
	}

	async startAndWaitForPort() {
		const container = this.ctx.container;
		if (!container.running) {
			container.start({ image: container.images.base, instance: "standard-1", enableInternet: false });
			await this.ctx.storage.put("version", this.version);
		}
		this.observeExit();
		await container.setInactivityTimeout(SLEEP_AFTER_MS);
		const port = container.getTcpPort(PORT);
		for (let attempt = 0; attempt < 240; attempt++) {
			try {
				const res = await port.fetch("http://container/", { signal: AbortSignal.timeout(2000) });
				await res.body?.cancel();
				if (res.ok) return;
			} catch {
				// not listening yet
			}
			await scheduler.wait(250);
		}
		throw new Error(`container did not become ready on port ${PORT}`);
	}

	observeExit() {
		if (this.monitoring) return;
		this.monitoring = this.ctx.container
			.monitor()
			.then(() => console.log("container exited"))
			.catch((e) => console.error("container failed", e))
			.finally(() => {
				this.monitoring = undefined;
				this.ready = false;
			});
		this.ctx.waitUntil(this.monitoring);
	}
}

export default {
	async fetch(request, env) {
		// One shared instance: the demo is light, and gradio keeps session state in memory.
		return env.APP.getByName("demo").fetch(request);
	},
};
