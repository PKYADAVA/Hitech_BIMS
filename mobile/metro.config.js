// Learn more https://docs.expo.dev/guides/customizing-metro
const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");

const appJson = require("./app.json");

const config = getDefaultConfig(__dirname);

/**
 * Pin `zustand` to its CommonJS build on web.
 *
 * zustand v4's ESM build guards its dev warnings with `import.meta.env.MODE` (a
 * Vite-ism). Metro serves the web bundle as a classic <script>, where
 * `import.meta` is a SyntaxError — it aborts the entire bundle before React
 * mounts, so the symptom is a blank page with a single console error.
 *
 * Why only web: Metro applies an `import` condition implicitly for ESM syntax,
 * and zustand's exports map resolves that to ./esm/index.mjs. Native never gets
 * there, because Metro also applies a `react-native` condition, which zustand
 * lists first and points at the CJS entry. This remap hands web the same file
 * native already resolves, so native behaviour is unchanged.
 *
 * Setting resolver conditions cannot fix this: the `import` condition is added
 * from the import syntax and is not removable via unstable_conditionNames.
 *
 * Revisit on the zustand v5 upgrade — v5 drops the `import.meta` usage.
 */
const ZUSTAND_CJS = path.join(__dirname, "node_modules", "zustand", "index.js");

config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (platform === "web" && moduleName === "zustand") {
    return { type: "sourceFile", filePath: ZUSTAND_CJS };
  }
  return context.resolveRequest(context, moduleName, platform);
};

/**
 * Dev-only API proxy for the web build.
 *
 * The browser enforces CORS and the backend sends no Access-Control-* headers,
 * so a direct call from http://localhost:8081 to the API origin is blocked
 * before the app ever sees a response (axios reports it as a bare network
 * error, with no status to report). Native has no such restriction, which is
 * why the phone works against the same endpoint.
 *
 * Forwarding /api/* through Metro makes the request same-origin, so CORS never
 * applies. This runs only in the Metro dev server — it has no effect on any
 * production build, and native still calls the API directly.
 *
 * The upstream is derived from the same config the app reads, so the two can't
 * drift.
 */
const UPSTREAM = new URL(
  process.env.EXPO_PUBLIC_API_BASE_URL || appJson.expo.extra.apiBaseUrl
);
const PROXY_PREFIX = UPSTREAM.pathname.replace(/\/$/, "");
const transport = UPSTREAM.protocol === "https:" ? require("https") : require("http");

config.server = {
  ...config.server,
  enhanceMiddleware: (metroMiddleware) => (req, res, next) => {
    if (!req.url || !req.url.startsWith(`${PROXY_PREFIX}/`)) {
      return metroMiddleware(req, res, next);
    }

    // Rewrite Host so virtual-hosted backends route correctly, and drop the
    // browser's Origin/Referer so the upstream sees a plain server-side call.
    const headers = { ...req.headers, host: UPSTREAM.host };
    delete headers.origin;
    delete headers.referer;

    const upstreamReq = transport.request(
      {
        protocol: UPSTREAM.protocol,
        hostname: UPSTREAM.hostname,
        port: UPSTREAM.port || undefined,
        method: req.method,
        path: req.url,
        headers,
      },
      (upstreamRes) => {
        res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
        upstreamRes.pipe(res);
      }
    );

    upstreamReq.on("error", (err) => {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: `API proxy failed: ${err.message}` }));
    });

    req.pipe(upstreamReq);
  },
};

module.exports = config;
