# Development guide

## Page functions in src/app.js

| Function | Page |
|---|---|
| `landing()` | Marketing website |
| `auth(signup)` | Login and registration |
| `onboard()`, `onboardResult()` | Questions and result |
| `dashboard()` | Learning workspace |
| `contestPage(id)` | Contest list/details |
| `portfolio()` | Builder and allocation controls |
| `academy(id)` | Courses and lesson detail/quiz |
| `insights()` | Portfolio review and journal |
| `marketplace()` | Planned services |
| `social()` | Reflections feed |
| `profile()` | User settings |
| `legal(kind)`, `resetPassword()` | Supporting pages |

`shell()` contains shared app navigation. `render()` resolves the current hash and updates the root. Delegated click/input/change/submit handlers near the end of the module perform demo actions. `state` is local browser state, `save()` persists it, and `toast()` displays feedback.

## Connect login first

1. Import `authApi` and `profileApi` from `./api/services.js`.
2. Make the delegated submit callback async, add `try/catch`, and disable the submit button while the request is pending.
3. For login, pass the form email/password to `authApi.login`.
4. Load `profileApi.get()` after a successful login. Update the user display state from the response, then navigate to the dashboard.
5. Handle invalid credentials and network failures visibly. Do not navigate as though the request succeeded.
6. Implement initial session loading and protected-route checks; the current demo intentionally has none.

Example of the request call inside the existing auth branch:

```js
await authApi.login({
  email: String(data.get('email')),
  password: String(data.get('password')),
});
const me = await profileApi.get();
state.name = me.displayName;
location.hash = '/dashboard';
```

This is a proposed integration pattern. Align response fields with your backend contract and add loading/error handling around it.

## Replace demo resources gradually

Move API-backed results into dedicated resource state instead of overwriting the exported demo constants. Render loading/error/empty states while requests resolve. Keep API failures distinct from empty lists. Cancel stale stock searches with AbortController when a new query replaces them.

Percentages in the demo are whole numbers; the proposed backend contract uses basis points (`percent * 100`). Enforce the total, holding caps, contest deadline, eligible stocks and ownership on the backend even if the UI validates them.

Replace `stats()`, SVG `chart()`, `donut()`, and `leaders()` as well as the builder data: these currently show independent illustrative values. They are not calculated from a user's submitted holdings.

The original prototype is a single app module; the file is intentionally retained for behavior fidelity. As it grows, move page templates into `src/pages/`, state into `src/state/`, and controllers into `src/controllers/`. Keep imports explicit so page modules do not rely on globals.

## Deployment

Build using `npm run build`. Serve generated `dist/` as static assets. Hash routing works without server-side SPA route rewrites. Route `/api` requests to your backend in your production server; development proxy configuration is not deployed.

This exported project is separate from the hosted Sites checkout. Customize and version it in your own Git repository.
