const HOST = "cf-test.ends0culus.com";
const SOURCE = "https://vote.ends0culus.com/_cf-trial";
const PAGES = new Map([
  ["/", "/index.html"],
  ["/index.html", "/index.html"],
  ["/trial.js", "/trial.js"],
  ["/trial.css", "/trial.css"],
  ["/samples/survey.js", "/samples/survey.js"],
  ["/samples/survey.css", "/samples/survey.css"],
]);

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.hostname !== HOST) return new Response("请从测试域名进入。", {status: 404});
    const isSubmit = url.pathname === "/_cf-trial/api";
    const path = isSubmit ? "/api" : PAGES.get(url.pathname);
    if (!path) return new Response(null, {status: 404});
    if (isSubmit ? request.method !== "POST" : !["GET", "HEAD"].includes(request.method)) {
      return new Response(null, {status: 405});
    }
    const headers = new Headers();
    if (isSubmit) {
      if (request.headers.get("Origin") !== "https://" + HOST) return new Response(null, {status: 403});
      if (request.headers.get("Content-Type")?.split(";")[0].trim() !== "application/json") {
        return new Response(null, {status: 415});
      }
      headers.set("Origin", "https://" + HOST);
      headers.set("Content-Type", "application/json");
    }
    try {
      const upstream = await fetch(SOURCE + path, {
        method: request.method, headers, body: isSubmit ? request.body : undefined,
        redirect: "manual", cache: "no-store",
      });
      if (upstream.status >= 300 && upstream.status < 400) return new Response(null, {status: 502});
      const response = new Response(upstream.body, upstream);
      response.headers.delete("Set-Cookie");
      response.headers.set("Cache-Control", "no-store");
      response.headers.set("X-Robots-Tag", "noindex, nofollow");
      response.headers.set("X-Content-Type-Options", "nosniff");
      response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
      return response;
    } catch {
      return new Response("暂时无法连接香港测试服务，请稍后重试。", {
        status: 502, headers: {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"},
      });
    }
  },
};
