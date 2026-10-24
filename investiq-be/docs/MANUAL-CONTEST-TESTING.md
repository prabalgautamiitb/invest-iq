# Test contests end to end from the frontend

Normal contests follow the reviewed exchange calendar. They start at a supported session open, lock entries beforehand, and obtain standings from published end-of-day prices. Admin access does not bypass deadlines or produce an immediate valuation. Starting a contest at the current minute would also leave no entry window in which learners could confirm portfolios.

Use the manual sandbox to test those rules in a few minutes. It runs the actual frontend, identity, contest, submission, valuation, standings and coach services against a disposable PostgreSQL database and a controllable **market/contest** clock. Password/session/email expiry and other domains keep normal wall-clock time.

## Start

Keep Docker Desktop and the normal PostgreSQL/Redis/Mailpit infrastructure running. From the project root:

```bash
# First time, if frontend dependencies are missing:
cd investiq-fe
npm ci
cd ../investiq-be

# Start a fresh manual sandbox:
uv run --locked python scripts/manual_sandbox.py
```

If already in the project root with dependencies installed, use `cd investiq-be` before the last command. The runner starts both the API and Vite:

- Control page: **http://127.0.0.1:8082/__sandbox__**
- Sandbox frontend: **http://127.0.0.1:5175**
- Email inbox: **http://localhost:8025**

The normal app at port 5173/8080 stays separate. Keep the printed terminal running. Ctrl+C stops the sandbox/frontend and deletes its temporary database. Restart the same command for an empty run. Ports 8082 and 5175 must be free; no additional Celery worker or Beat is needed for this sandbox.

## Accounts, administration and publication

1. Open the sandbox frontend and register a **fresh test account**. Existing normal-app accounts are not copied into the sandbox.
2. Verify that account using its newest Mailpit verification message. The link should point to `127.0.0.1:5175`.
3. On the control page, enter the verified sandbox email and click **Enable sandbox admin**. Reload the frontend so it obtains the new role.
4. Open **Contests → Manage InvestIQ contests → Add InvestIQ contest**. Keep the suggested dates, save the draft, then click **Publish and freeze rules**.
5. Use separate browser profiles/incognito windows for two learner accounts at **the same sandbox frontend URL**. Register and verify them. Find the public contest and join it. Joining takes the learner to My Contests; open its Portfolio from there.
6. Build different valid portfolios, save each draft, review the server calculation, then **Confirm contest submission**. A saved draft alone does not qualify for standings. Hosting a contest does not automatically join the admin.

The initial virtual time is **October 14, 2026, 18:30 IST**. The sandbox's suggested schedule is:

| Event | Virtual IST time |
| --- | --- |
| Entry opens | October 14, 18:30 |
| Entry closes | October 15, 09:10 |
| Contest starts | October 15, 09:15 |
| First session closes | October 15, 15:30 |
| First prices publish | October 15, 18:00 |
| Contest ends | October 16, 15:30 |
| Final prices publish | October 16, 18:00 |

These dates fit the checked-in original synthetic price fixture. Keep this schedule for a complete supported scenario; arbitrary dates still fail normal calendar/coverage validation. You can create public/private community contests, invitations, capacity/cancellation cases or multiple public admin contests while the virtual entry window remains open.

## Advance the clock

Finish account/contest/submission setup first. Then use the control page buttons:

| Button | What to inspect in the frontend |
| --- | --- |
| Entry locked — contest running | Joining/submitting is closed; confirmed submissions remain recorded; standings wait for prices |
| First session closed — prices await publication | The session has closed, but no ranking is published yet |
| First valuation — standings available | At virtual October 15, 18:30 IST, the actual valuation service calculates values, returns, benchmark comparisons, contributions and ranks |
| Final valuation — contest completed | At virtual October 16, 18:30 IST, the next price batch changes portfolio values and finalizes the contest and standings |

After each step, use **Refresh results** in Performance/Leaderboard, refresh My Contests, or reload the page. Server-backed contest pages do not all poll continuously. Clock advancement invokes the actual valuation sweep; no values, ranks or submissions are injected.

The clock moves forward only because confirmed submissions and published valuation records are immutable. To repeat pre-entry tests after advancing, stop/restart the runner. The **Entry open** button can rerun the current initial stage but cannot rewind finalized history.

Suggested checks:

- Public discovery, admin draft visibility, publication, private invitations and joining/capacity.
- Minimum/maximum holdings, allocation total, position limits, quantity conversion, simulated fees and residual cash.
- Draft reload, preview, confirmation, versioned resubmission before lock, and rejected writes after lock.
- Confirmed count versus ranked count, private Performance versus public Leaderboard, own-name privacy, rank ordering and differing portfolio values.
- First snapshot versus final snapshot, completed contest history and repeated valuation without duplicate snapshots.

## AI coach

After valuation, request a coach report through Insights. Click **Process one queued coach report** on the control page, then refresh/wait for the frontend report status. This uses the configured local Ollama model through the actual durable/checkpointed coach workflow; no browser-test mock is enabled. Ollama must be running with the selected model installed. Core contest testing works without Ollama.

## Isolation and controls

The standalone runner creates only databases named `investiq_manual_sandbox_<random UUID>`, migrates/seeds reviewed definitions and synthetic market data, and drops its database on graceful exit. It never imports real users, balances or activity. A separate cookie name prevents sandbox sign-in from replacing the normal app's session even though browser cookies are shared across ports. Development emails are forced to local Mailpit, and the AI provider is fixed to Ollama for this runner.

Controls bind to loopback, check the expected Host, require the control page's same-origin request plus a random per-run token for mutations, and reject clock rewinds. The clock, promotion and manual-worker routes exist only in `scripts/manual_sandbox.py`, which is excluded from the application image/wheel; they are not production API settings or endpoints. Do not expose the sandbox ports through a tunnel or public bind address.

Abrupt machine shutdown/SIGKILL cannot run cleanup. If that happens, an operator may remove only the orphaned `investiq_manual_sandbox_*` database after stopping its processes. Normal exit through Ctrl+C performs cleanup automatically. Unrelated databases and the normal Compose services are preserved.

Verification covers cookie isolation, loopback/Host/token/Origin checks, verified admin promotion, the normal platform-contest creation/publication/submission API, pending results before publication, first/final snapshot changes and terminal completion. Manual browser verification also exercised admin creation, learner signup/join/confirmation and two ranked portfolios through final results.
