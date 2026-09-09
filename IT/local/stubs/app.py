#!/usr/bin/env python3

"""
Every non-AWS dependency of a HealthBot run, in one process:

    :8080  a fake storefront that satisfies checks/site.py's Playwright
           journey (search -> product -> add to cart -> checkout) and
           answers every ping URL
    :8081  /nr/...     the New Relic v2 API subset checks/nr.py calls
           /ga/...     GA discovery document, token endpoint and the
                       realtime data endpoint checks/ga.py calls
           /slack/...  a chat.postMessage shim that relays the bot's real
                       Slack blocks into Mattermost
           /control    chaos switches (checkout_down, pings_down, ga_surge,
                       nr_slow) so alerts can be staged on purpose
           /health     liveness for healthbot-local status

AWS itself is MiniStack's job, not this file's. Runs only inside the
IT/local compose stack; nothing here is deployable.
"""

import asyncio
import json
import os
import re
import time
from html import escape

from aiohttp import ClientSession, web

MATTERMOST_URL = os.environ.get("MATTERMOST_URL", "http://mattermost:8065")
# The base the *host-side* healthbot process reaches this container on; it is
# templated into the GA discovery document, which is why it must be the
# published port, not the compose-internal name.
PUBLIC_API_BASE = os.environ.get("PUBLIC_API_BASE", "http://localhost:8081")

MM_EMAIL = "sre@local.test"
MM_USERNAME = "sre"
MM_PASSWORD = "SuperSecret-123"  # pragma: allowlist secret
MM_TEAM = "sre"

# Chaos switches, togglable at runtime through /control
STATE = {
    "checkout_down": False,
    "pings_down": False,
    "ga_surge": False,
    "nr_slow": False,
}

# Filled by the Mattermost bootstrap task
MATTERMOST = {"webhook_url": None, "token": None, "channel_id": None}


# --------------------------------------------------------------------------
# Storefront (:8080) — the minimum DOM that carries checks/site.py end to end
# --------------------------------------------------------------------------

PAGE_CSS = """
body { font-family: sans-serif; margin: 2rem; background: #f4f6f8; color: #1c2733; }
.products-grid { display: flex; gap: 1rem; }
.product-item-photo { display: block; width: 160px; height: 120px; background: #7fb3d5;
    border-radius: 6px; color: #fff; padding: 8px; text-decoration: none; }
.swatch-attribute { display: inline-block; padding: 6px 10px; margin: 4px;
    border: 1px solid #888; border-radius: 4px; cursor: pointer; }
.add-to-cart-title { padding: 10px 18px; font-size: 1rem; cursor: pointer; }
.recommended-products-modal-content { display: none; position: fixed; inset: 20% 25%;
    background: #fff; border: 2px solid #444; border-radius: 8px; padding: 2rem; }
"""


def html(title: str, body: str) -> web.Response:
    doc = (
        f"<!DOCTYPE html><html><head><title>{title}</title>"
        f"<style>{PAGE_CSS}</style></head><body>{body}</body></html>"
    )
    return web.Response(text=doc, content_type="text/html")


async def store_home(request: web.Request) -> web.Response:
    return html(
        "Example Local Storefront",
        """
        <h1>Example Store — local stand-in</h1>
        <input id="search" type="text" placeholder="Search products" />
        <script>
        document.getElementById('search').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                location.href = '/catalogsearch/result/?q=' +
                    encodeURIComponent(e.target.value);
            }
        });
        </script>
        """,
    )


async def store_search(request: web.Request) -> web.Response:
    query = request.rel_url.query.get("q", "")
    return html(
        f"Search results for: {query}",
        f"""
        <h1 class="page-title">Search results for: '{query}'</h1>
        <div class="products-grid">
            <a class="product-item-photo"
               href="/product/infinity-round-neck-top.html">Infinity Round Neck Top</a>
            <a class="product-item-photo"
               href="/product/cherokee-v-neck.html">Cherokee V-Neck</a>
        </div>
        """,
    )


async def store_product(request: web.Request) -> web.Response:
    return html(
        "Infinity Round Neck Scrub Top",
        """
        <h1>Infinity Round Neck Scrub Top</h1>
        <div class="swatch-attribute color">Pewter</div>
        <div class="swatch-attribute size">M</div>
        <button class="add-to-cart-title">Add to Cart</button>
        <div class="recommended-products-modal-content">
            <p>Added to cart — customers also bought:</p>
            <a class="popup-button primary" href="/checkout">Proceed to Checkout</a>
        </div>
        <script>
        document.querySelector('.add-to-cart-title').addEventListener('click', () => {
            document.querySelector('.recommended-products-modal-content')
                .style.display = 'block';
        });
        </script>
        """,
    )


async def store_checkout(request: web.Request) -> web.Response:
    if STATE["checkout_down"]:
        # The title check is the assertion site.py makes, so an outage is a
        # wrong title on a 200, exactly how a broken checkout usually looks.
        return html("Service Unavailable", "<h1>Something went wrong</h1>")
    return html("Checkout", "<h1>Checkout</h1><p>Guest checkout form goes here.</p>")


async def store_any(request: web.Request) -> web.Response:
    # Every other path is a ping target; checks/pings.py wants a flat 200.
    if STATE["pings_down"]:
        raise web.HTTPServiceUnavailable(text="staged outage")
    # escape(): the path is attacker-controlled even here, and reflecting
    # it raw made this stub a working XSS demo rather than a storefront.
    # The rule matches f-string HTML construction regardless of escaping;
    # pinned rather than silenced, and only once the value is escaped.
    # nosemgrep: python.django.security.injection.raw-html-format.raw-html-format
    return html("Example Local Storefront", f"<h1>{escape(request.path)}</h1><p>ok</p>")


# --------------------------------------------------------------------------
# New Relic stub (:8081/nr) — the applications.json subset checks/nr.py reads
# --------------------------------------------------------------------------


async def nr_applications(request: web.Request) -> web.Response:
    app_ms, web_s = (2300.0, 6.2) if STATE["nr_slow"] else (187.0, 1.4)
    return web.json_response(
        {
            "applications": [
                {
                    "id": 1,
                    "name": request.rel_url.query.get("filter[name]", "example-web"),
                    "health_status": "green",
                    "reporting": True,
                    "application_summary": {
                        "response_time": app_ms,
                        "throughput": 231.0,
                        "error_rate": 0.2,
                        "apdex_target": 0.5,
                        "apdex_score": 0.97,
                        "host_count": 4,
                        "instance_count": 4,
                    },
                    "end_user_summary": {
                        "response_time": web_s,
                        "throughput": 120.0,
                        "apdex_target": 7.0,
                        "apdex_score": 0.93,
                    },
                }
            ]
        }
    )


# --------------------------------------------------------------------------
# Google Analytics stub (:8081/ga) — discovery + token + realtime endpoint
# --------------------------------------------------------------------------


async def ga_discovery(request: web.Request) -> web.Response:
    # Just enough discovery document for data().realtime().get(); rootUrl is
    # the published base so the generated client calls back into this stub.
    return web.json_response(
        {
            "kind": "discovery#restDescription",
            "id": "analytics:v3",
            "name": "analytics",
            "version": "v3",
            "rootUrl": f"{PUBLIC_API_BASE}/",
            "servicePath": "ga/analytics/v3/",
            "baseUrl": f"{PUBLIC_API_BASE}/ga/analytics/v3/",
            "protocol": "rest",
            "resources": {
                "data": {
                    "resources": {
                        "realtime": {
                            "methods": {
                                "get": {
                                    "id": "analytics.data.realtime.get",
                                    "path": "data/realtime",
                                    "httpMethod": "GET",
                                    "parameters": {
                                        "ids": {
                                            "type": "string",
                                            "required": True,
                                            "location": "query",
                                        },
                                        "metrics": {
                                            "type": "string",
                                            "required": True,
                                            "location": "query",
                                        },
                                        "dimensions": {"type": "string", "location": "query"},
                                    },
                                    "parameterOrder": ["ids", "metrics"],
                                    "response": {"$ref": "RealtimeData"},
                                }
                            }
                        }
                    }
                }
            },
            "schemas": {"RealtimeData": {"id": "RealtimeData", "type": "object"}},
        }
    )


async def ga_token(request: web.Request) -> web.Response:
    # google-auth signs a real JWT with the seeded throwaway key and posts it
    # here; nothing verifies it — the exercise is the client-side code path.
    return web.json_response(
        {"access_token": "local-ga-access-token", "expires_in": 3600, "token_type": "Bearer"}
    )


async def ga_realtime(request: web.Request) -> web.Response:
    active = "934" if STATE["ga_surge"] else "137"
    return web.json_response(
        {
            "kind": "analytics#realtimeData",
            "totalResults": 1,
            "totalsForAllResults": {"rt:activeUsers": active},
        }
    )


# --------------------------------------------------------------------------
# Slack shim (:8081/slack) — chat.postMessage relayed into Mattermost
# --------------------------------------------------------------------------


def blocks_to_markdown(blocks: list) -> str:
    """
    Flatten the bot's Slack Block Kit payload into Mattermost markdown. Only
    the block shapes slack.j2 actually produces are handled; anything else
    degrades to its raw text.
    """
    lines = []
    for block in blocks:
        kind = block.get("type")
        if kind == "header":
            lines.append(f"## {block.get('text', {}).get('text', '')}")
        elif kind == "context":
            texts = [
                element.get("text", "")
                for element in block.get("elements", [])
                if element.get("type") == "mrkdwn"
            ]
            lines.append("\n".join(texts))
        elif kind == "section":
            text = block.get("text", {}).get("text", "")
            if text:
                lines.append(text)
            fields = [field.get("text", "") for field in block.get("fields", [])]
            # slack.j2 writes fields as label/value pairs
            for label, value in zip(fields[0::2], fields[1::2], strict=False):
                lines.append(f"- {label} {value}")
    return "\n\n".join(line for line in lines if line)


def parse_blocks(raw: str):
    # slack.j2 emits trailing commas inside arrays; Slack tolerates them and
    # json.loads does not, so strip them before parsing.
    try:
        return json.loads(re.sub(r",\s*([\]}])", r"\1", raw))
    except (json.JSONDecodeError, TypeError):
        return None


async def slack_post_message(request: web.Request) -> web.Response:
    # slack_sdk sends chat.postMessage as a JSON body when blocks are
    # attached, urlencoded otherwise — accept both, or the relay silently
    # degrades to the placeholder text.
    if request.content_type == "application/json":
        payload = await request.json()
    else:
        payload = dict(await request.post())

    raw_blocks = payload.get("blocks", "")
    if isinstance(raw_blocks, str):
        blocks = parse_blocks(raw_blocks)
    else:
        blocks = raw_blocks  # already a parsed list in a JSON body
    if blocks:
        message = blocks_to_markdown(blocks)
    else:
        message = payload.get("text") or "(empty HealthBot message)"

    delivered = await post_to_mattermost(message)
    if not delivered:
        # Surface the failure to the caller: SlackNotificationAware logs a
        # SlackApiError body, which is more honest than a swallowed relay.
        return web.json_response({"ok": False, "error": "mattermost_unreachable"}, status=502)
    return web.json_response(
        {"ok": True, "channel": payload.get("channel", ""), "ts": str(time.time())}
    )


# --------------------------------------------------------------------------
# Mattermost bootstrap: first user -> team -> incoming webhook, idempotently
# --------------------------------------------------------------------------


async def mm_request(session, method: str, path: str, token: str = None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with session.request(
        method, f"{MATTERMOST_URL}/api/v4{path}", headers=headers, **kwargs
    ) as response:
        try:
            body = await response.json(content_type=None)
        except (json.JSONDecodeError, ValueError):
            body = {}
        return response, body if body is not None else {}


async def bootstrap_mattermost() -> bool:
    if MATTERMOST["webhook_url"]:
        return True
    try:
        async with ClientSession() as session:
            # login, creating the first (therefore admin) user if needed
            response, _ = await mm_request(
                session,
                "POST",
                "/users/login",
                json={"login_id": MM_EMAIL, "password": MM_PASSWORD},
            )
            if response.status != 200:
                await mm_request(
                    session,
                    "POST",
                    "/users",
                    json={"email": MM_EMAIL, "username": MM_USERNAME, "password": MM_PASSWORD},
                )
                response, _ = await mm_request(
                    session,
                    "POST",
                    "/users/login",
                    json={"login_id": MM_EMAIL, "password": MM_PASSWORD},
                )
                if response.status != 200:
                    return False
            token = response.headers.get("Token")
            _, me = await mm_request(session, "GET", "/users/me", token)

            response, team = await mm_request(session, "GET", f"/teams/name/{MM_TEAM}", token)
            if response.status != 200:
                response, team = await mm_request(
                    session,
                    "POST",
                    "/teams",
                    token,
                    json={"name": MM_TEAM, "display_name": "SRE", "type": "O"},
                )
                if response.status != 201:
                    return False
            await mm_request(
                session,
                "POST",
                f"/teams/{team['id']}/members",
                token,
                json={"team_id": team["id"], "user_id": me["id"]},
            )

            _, channel = await mm_request(
                session, "GET", f"/teams/{team['id']}/channels/name/town-square", token
            )

            response, hooks = await mm_request(
                session, "GET", f"/hooks/incoming?team_id={team['id']}", token
            )
            hook = next(
                (
                    h
                    for h in (hooks if isinstance(hooks, list) else [])
                    if h.get("display_name") == "HealthBot"
                ),
                None,
            )
            if hook is None:
                response, hook = await mm_request(
                    session,
                    "POST",
                    "/hooks/incoming",
                    token,
                    json={
                        "channel_id": channel["id"],
                        "display_name": "HealthBot",
                        "description": "HealthBot SRE alerts (local stack)",
                    },
                )
                if response.status != 201:
                    return False

            MATTERMOST.update(
                webhook_url=f"{MATTERMOST_URL}/hooks/{hook['id']}",
                token=token,
                channel_id=channel["id"],
            )
            print(f"mattermost ready: webhook {hook['id']} -> ~town-square", flush=True)
            return True
    except Exception as err:
        print(f"mattermost bootstrap failed, will retry: {err!r}", flush=True)
        return False


async def post_to_mattermost(message: str) -> bool:
    if not await bootstrap_mattermost():
        return False
    try:
        async with ClientSession() as session:
            async with session.post(
                MATTERMOST["webhook_url"], json={"text": message, "username": "HealthBot"}
            ) as response:
                if response.status == 200:
                    return True
            # Webhook refused (e.g. username override disallowed config
            # drift) — fall back to posting directly as the admin user.
            _, _ = await mm_request(
                session,
                "POST",
                "/posts",
                MATTERMOST["token"],
                json={"channel_id": MATTERMOST["channel_id"], "message": message},
            )
            return True
    except Exception as err:
        print(f"mattermost delivery failed: {err!r}", flush=True)
        return False


async def bootstrap_loop() -> None:
    for _ in range(60):  # Mattermost preview takes a while on first boot
        if await bootstrap_mattermost():
            return
        await asyncio.sleep(5)
    print("mattermost bootstrap gave up; will retry on first message", flush=True)


async def start_bootstrap(app) -> None:
    # aiohttp awaits startup handlers, so the retry loop must detach into a
    # task or the server would not accept connections until Mattermost is up.
    app["mm_bootstrap"] = asyncio.create_task(bootstrap_loop())


# --------------------------------------------------------------------------
# Control and health
# --------------------------------------------------------------------------


async def control(request: web.Request) -> web.Response:
    if request.method == "POST":
        changes = await request.json()
        unknown = set(changes) - set(STATE)
        if unknown:
            raise web.HTTPBadRequest(text=f"unknown switches: {sorted(unknown)}")
        STATE.update({key: bool(value) for key, value in changes.items()})
    return web.json_response(STATE)


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "mattermost_ready": bool(MATTERMOST["webhook_url"])})


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


def build_store() -> web.Application:
    app = web.Application()
    app.router.add_get("/", store_home)
    app.router.add_get("/catalogsearch/result/", store_search)
    app.router.add_get("/product/{slug}", store_product)
    app.router.add_get("/checkout", store_checkout)
    app.router.add_route("*", "/{tail:.*}", store_any)
    return app


def build_api() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_route("*", "/control", control)
    app.router.add_get("/nr/v2/applications.json", nr_applications)
    app.router.add_get("/ga/discovery", ga_discovery)
    app.router.add_post("/ga/token", ga_token)
    app.router.add_get("/ga/analytics/v3/data/realtime", ga_realtime)
    app.router.add_post("/slack/chat.postMessage", slack_post_message)
    app.on_startup.append(start_bootstrap)
    return app


async def serve() -> None:
    store_runner = web.AppRunner(build_store())
    api_runner = web.AppRunner(build_api())
    await store_runner.setup()
    await api_runner.setup()
    await web.TCPSite(store_runner, "0.0.0.0", 8080).start()
    await web.TCPSite(api_runner, "0.0.0.0", 8081).start()
    print("stubs up: storefront :8080, apis :8081", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(serve())
