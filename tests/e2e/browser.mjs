// Chromium against the server image: the studio over https behind Caddy, the TLS proxy (tests/e2e/tls-proxy.yaml).
//
//   scripts/browser-e2e.sh            # starts the stack behind the proxy, creates a tenant and runs this file
//
// The script passes the stack's state in the environment:
//   NODESTRO_BROWSER_ORIGIN   https://localhost:<port> (Caddy)
//   NODESTRO_BROWSER_CA       Caddy's local root certificate (PEM file), to verify the proxy's certificate
//   NODESTRO_BROWSER_SETUP    a setup link of a new tenant (its first login becomes the owner)
//   NODESTRO_BROWSER_TENANT   that tenant's id
//   NODESTRO_BROWSER_USERS    compose/.secrets/users.json (the Dex accounts)
//   NODESTRO_BROWSER_SHOTS    optional: a directory for a screenshot of the page that failed
//
// Covers:
// - TLS: the proxy's certificate is valid for localhost under Caddy's authority; Chromium refuses the studio while it
//   does not trust that certificate, and plain http on the TLS port never reaches the studio.
// - The first login through a setup link: the studio's origin sends the browser to Dex (OpenID Connect), the callback
//   on the https origin sets `__Host-nodestro-session` (Secure, HttpOnly, SameSite=Lax, Path=/, no Domain) and drops
//   the login cookie, page scripts cannot read the session, the server sends HSTS, and the studio renders the signed-in
//   user's workflows page without console errors.
// - Sign out in the studio: the session ends, the studio itself sends the browser to Dex again, and a second login
//   comes back to the studio.
// - Refusals: a wrong password stays at Dex with no session; an account without a tenant gets
//   `identity.no_tenant` and no session; a sign-in code taken to another browser (without the login cookie) gets
//   `identity.login_expired` and no session.

import { createRequire } from "node:module";
import { X509Certificate, createHash } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import tls from "node:tls";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

function setting(name) {
  const value = process.env[name];
  if (!value) {
    console.error(`${name} is not set (scripts/browser-e2e.sh runs this test)`);
    process.exit(2);
  }
  return value;
}

const origin = setting("NODESTRO_BROWSER_ORIGIN");
const caFile = setting("NODESTRO_BROWSER_CA");
const setupLink = setting("NODESTRO_BROWSER_SETUP");
const tenant = setting("NODESTRO_BROWSER_TENANT");
const users = JSON.parse(readFileSync(setting("NODESTRO_BROWSER_USERS"), "utf8"));
const shots = process.env.NODESTRO_BROWSER_SHOTS;
const DEX = "http://localhost:5556/dex/";
const SESSION = "__Host-nodestro-session";
const LOGIN = "__Host-nodestro-login";
const { hostname, port } = new URL(origin);

function check(condition, message) {
  if (!condition) throw new Error(message);
  console.log(`ok  ${message}`);
}

/** The proxy's certificate, verified against Caddy's root (retried while Caddy starts). */
async function proxyCertificate(timeout = 60_000) {
  const ca = readFileSync(caFile);
  const deadline = Date.now() + timeout;
  for (;;) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = tls.connect({ host: hostname, port: Number(port), servername: hostname, ca }, () => {
          const certificate = socket.getPeerX509Certificate();
          socket.end();
          resolve(certificate);
        });
        socket.on("error", reject);
      });
    } catch (error) {
      if (Date.now() > deadline || (error.code && !["ECONNREFUSED", "ECONNRESET"].includes(error.code))) throw error;
      await new Promise((done) => setTimeout(done, 1000));
    }
  }
}

/** Whether a TLS connection with Node's default (public) roots is refused: the certificate is not publicly trusted. */
function refusedWithoutCa() {
  return new Promise((resolve) => {
    const socket = tls.connect({ host: hostname, port: Number(port), servername: hostname }, () => {
      socket.end();
      resolve(null);
    });
    socket.on("error", (error) => resolve(error.code ?? error.message));
  });
}

const certificate = await proxyCertificate();
check(certificate instanceof X509Certificate && certificate.checkHost(hostname) === hostname, `The proxy's certificate is valid for ${hostname} under Caddy's authority`);
const refusal = await refusedWithoutCa();
check(refusal !== null, `Without Caddy's authority the certificate is refused (${refusal})`);
// Chromium trusts exactly this certificate's public key, nothing else (no --ignore-certificate-errors).
const spki = createHash("sha256").update(certificate.publicKey.export({ type: "spki", format: "der" })).digest("base64");

const plain = await fetch(`http://${hostname}:${port}/`).catch((error) => error);
check(
  plain instanceof Error || (plain.status >= 400 && !(await plain.text()).includes('<div id="root"')),
  `Plain http on the TLS port never reaches the studio (${plain instanceof Error ? plain.message : plain.status})`,
);

// A browser that does not trust the proxy's certificate refuses the studio.
{
  const untrusting = await chromium.launch();
  try {
    const page = await untrusting.newPage();
    const failure = await page.goto(origin).then(
      () => null,
      (error) => error.message,
    );
    check(failure !== null && /ERR_CERT_AUTHORITY_INVALID/.test(failure), "Chromium without the certificate refuses the studio (ERR_CERT_AUTHORITY_INVALID)");
  } finally {
    await untrusting.close();
  }
}

const browser = await chromium.launch({ args: [`--ignore-certificate-errors-spki-list=${spki}`] });
let current = null;

async function open() {
  const context = await browser.newContext({ locale: "en-US", viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`${page.url()}: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`${page.url()}: ${error.message}`));
  current = page;
  return { context, page, errors };
}

async function cookieNames(context) {
  return (await context.cookies(origin)).map((cookie) => cookie.name);
}

/** The Dex password form: wait for it, then submit the account's address and a password. */
async function signInAtDex(page, email, password) {
  await page.waitForURL((url) => url.href.startsWith(DEX), { timeout: 30_000 });
  await page.locator('input[name="login"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
}

/** The callback's answer (the response to https://…/api/auth/callback) for the next login. */
function callback(page) {
  return page.waitForResponse((response) => response.url().startsWith(`${origin}/api/auth/callback`), { timeout: 30_000 });
}

/** The signed-in studio: the workflows page with the user menu of `email`. */
async function studioFor(page, email) {
  await page.waitForURL((url) => url.origin === origin && !url.pathname.startsWith("/api/"), { timeout: 30_000 });
  await page.getByRole("heading", { name: "Workflows", exact: true }).waitFor({ timeout: 30_000 });
  await page.getByTestId("user-menu").filter({ hasText: email }).waitFor({ timeout: 30_000 });
}

/**
 * A login of `account` whose callback is held back: the callback URL (with the sign-in code) and the login cookie of
 * the browser that started it. Dex answers the password form with redirects to the callback, and route handlers never
 * see redirect targets, so the form's POST is sent from here and its redirects are followed by hand.
 */
async function heldBackLogin(account) {
  const { context, page } = await open();
  let held = null;
  await page.route(`${DEX}**`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    let response = await route.fetch({ maxRedirects: 0 });
    for (let hops = 0; hops < 10 && [302, 303].includes(response.status()); hops += 1) {
      const next = new URL(response.headers().location, response.url()).href;
      if (next.startsWith(`${origin}/api/auth/callback`)) {
        held = next;
        return route.fulfill({ status: 200, contentType: "text/plain", body: "held back by the test" });
      }
      response = await page.request.get(next, { maxRedirects: 0 });
    }
    return route.fulfill({ response });
  });
  await page.goto(`${origin}/api/auth/login`);
  await signInAtDex(page, account.email, account.password);
  await page.getByText("held back by the test").waitFor({ timeout: 30_000 });
  check(held !== null, "Dex sent the sign-in code to the callback on the https origin (held back)");
  const cookies = (await context.cookies(origin)).filter((cookie) => cookie.name === LOGIN);
  check(cookies.length === 1, "The browser that started the login holds the login cookie");
  await context.close();
  return { callback: held, cookies };
}

try {
  const alice = users.alice;

  // First login of the tenant's owner through the setup link.
  {
    const { context, page, errors } = await open();
    check(setupLink.startsWith(`${origin}/api/auth/login?setup=`), "The setup link points at the https origin of the proxy");
    const answer = callback(page);
    await page.goto(setupLink);
    check(page.url().startsWith(DEX), "The setup link sends the browser to the identity provider (Dex)");
    await signInAtDex(page, alice.email, alice.password);
    const response = await answer;
    const setCookie = (await response.headerValue("set-cookie")) ?? "";
    const session = setCookie.split("\n").find((line) => line.startsWith(`${SESSION}=`)) ?? "";
    check(response.status() === 303, "The callback on the https origin answers with a redirect into the studio");
    check(/;\s*Secure/i.test(session) && /;\s*HttpOnly/i.test(session) && /;\s*SameSite=Lax/i.test(session), "The session cookie is Secure, HttpOnly and SameSite=Lax");
    check(/;\s*Path=\/(;|$)/i.test(session) && !/;\s*Domain=/i.test(session), "The session cookie has Path=/ and no Domain (__Host- prefix rules)");
    await studioFor(page, alice.email);
    check(new URL(page.url()).protocol === "https:", `The studio renders over https for the signed-in owner (${page.url()})`);
    const jar = await context.cookies(origin);
    const stored = jar.find((cookie) => cookie.name === SESSION);
    check(stored?.secure && stored.httpOnly && stored.sameSite === "Lax" && stored.path === "/", "Chromium stored the session cookie with its flags");
    check(!jar.some((cookie) => cookie.name === LOGIN), "The login cookie is gone after the callback");
    check(!(await page.evaluate(() => document.cookie)).includes("nodestro"), "Page scripts cannot read the session cookie");
    const me = await page.evaluate(async () => {
      const reply = await fetch("/api/auth/me");
      return { status: reply.status, hsts: reply.headers.get("strict-transport-security"), body: await reply.json() };
    });
    check(me.status === 200 && me.body.tenant_id === tenant && me.body.role === "owner", "/api/auth/me from the page: the owner of the new tenant");
    check(Boolean(me.hsts) && /max-age=\d+/.test(me.hsts), `The server sends Strict-Transport-Security over https (${me.hsts})`);
    check(errors.length === 0, `No console errors while signing in and rendering the studio${errors.length ? `:\n  ${errors.join("\n  ")}` : ""}`);

    // Sign out in the studio: the start page asks for a new login, and the studio sends the browser to Dex.
    const loggedOutErrors = errors.length;
    await page.getByTestId("user-menu").locator("summary").click();
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL((url) => url.href.startsWith(DEX), { timeout: 30_000 });
    check(!(await cookieNames(context)).includes(SESSION), "Sign out ends the session; the studio sends the browser to Dex again");
    // The studio's own requests before the redirect are answered 401 (access.login_required); nothing else may fail.
    const unexpected = errors.slice(loggedOutErrors).filter((text) => !/status of 401/.test(text));
    check(unexpected.length === 0, `Only the expected 401 answers while signed out${unexpected.length ? `:\n  ${unexpected.join("\n  ")}` : ""}`);
    const again = callback(page);
    await signInAtDex(page, alice.email, alice.password);
    check((await again).status() === 303, "A second login (no setup link) comes back to the studio");
    await studioFor(page, alice.email);
    check((await cookieNames(context)).includes(SESSION), "Signed in again with a new session cookie");
    await context.close();
  }

  // A wrong password stays at Dex: no callback, no session.
  {
    const { context, page } = await open();
    let called = false;
    page.on("request", (request) => {
      if (request.url().startsWith(`${origin}/api/auth/callback`)) called = true;
    });
    await page.goto(`${origin}/api/auth/login`);
    await signInAtDex(page, alice.email, `${alice.password}-wrong`);
    await page.locator("#login-error").waitFor({ timeout: 30_000 });
    check(page.url().startsWith(DEX) && !called, "A wrong password is refused at Dex and never reaches the callback");
    check(!(await cookieNames(context)).includes(SESSION), "No session cookie after a wrong password");
    await context.close();
  }

  // An account without a tenant: the callback refuses it.
  {
    const { context, page } = await open();
    const answer = callback(page);
    await page.goto(`${origin}/api/auth/login`);
    await signInAtDex(page, users.mallory.email, users.mallory.password);
    const response = await answer;
    check(response.status() === 403 && (await response.json()).code === "identity.no_tenant", "An account without a tenant gets 403 identity.no_tenant");
    check(!(await cookieNames(context)).includes(SESSION), "No session cookie for an account without a tenant");
    await context.close();
  }

  // A sign-in code taken to another browser: the login is bound to the browser that started it.
  {
    const first = await heldBackLogin(alice);
    const other = await open();
    const response = await other.page.goto(first.callback);
    check(response.status() === 400 && (await response.json()).code === "identity.login_expired", "The callback in another browser gets 400 identity.login_expired");
    check(!(await cookieNames(other.context)).includes(SESSION), "No session cookie in the other browser");
    await other.context.close();
    // The control: a second held-back login, taken to a fresh browser together with the starting browser's login
    // cookie, signs in. So the refusal above came from the missing binding, not from a broken code. (The refused
    // callback used up the first login: the server consumes the login state before it checks the binding.)
    const second = await heldBackLogin(alice);
    const bound = await open();
    await bound.context.addCookies(second.cookies);
    const answer = callback(bound.page);
    await bound.page.goto(second.callback);
    check((await answer).status() === 303, "With the starting browser's login cookie the held-back code signs in");
    await studioFor(bound.page, alice.email);
    check((await cookieNames(bound.context)).includes(SESSION), "That browser holds a session");
    await bound.context.close();
  }

  console.log("browser test passed");
} catch (error) {
  console.error(`FAILED: ${error.message}`);
  if (current) {
    console.error(`page: ${current.url()}`);
    if (shots) {
      mkdirSync(shots, { recursive: true });
      await current.screenshot({ path: join(shots, "failure.png"), fullPage: true }).catch(() => {});
    }
  }
  process.exitCode = 1;
} finally {
  await browser.close();
}
