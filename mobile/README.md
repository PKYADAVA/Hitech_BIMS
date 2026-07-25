# Hitech BIMS — Mobile App (React Native / Expo)

A React Native (Expo + TypeScript) client for the Hitech BIMS `/api/v1/`
backend. This first slice ships **JWT login** and two **infinite-scroll**
transaction feeds — Broiler *Daily Entries* and Hatchery *Egg Purchases* — on a
reusable API + list foundation so new screens are a few lines each.

## Stack

| Concern | Choice |
|---|---|
| Runtime | Expo SDK 51 (managed) + TypeScript |
| Navigation | React Navigation (native-stack + bottom-tabs) |
| Server state | TanStack Query (`useInfiniteQuery`) |
| Auth/UI state | Zustand |
| HTTP | Axios (envelope unwrap + JWT auto-refresh interceptor) |
| Token storage | `expo-secure-store` (Keychain / Keystore) |

## Architecture (why screens stay thin)

```
src/
  config.ts                 API base URL resolution
  api/
    types.ts                Envelope / Pagination / AuthUser / ApiError
    tokenStore.ts           SecureStore-backed JWT storage (+ in-memory mirror)
    client.ts               axios: bearer + single-flight refresh + error mapping
    auth.ts                 me() / logout()
    resources.ts            generic list/get/create/update/delete (envelope-aware)
  query/
    queryClient.ts          shared React Query client
    useResourceList.ts      ONE infinite-scroll hook for any resource
  store/authStore.ts        session lifecycle (bootstrap/login/logout)
  components/
    ui.tsx                  Screen / Button / Field / Loading / EmptyOrError
    ResourceList.tsx        reusable list screen (pull-to-refresh + paging)
  screens/                  Login, Home, DailyEntries, EggPurchases
  navigation/RootNavigator  auth stack ⇄ app tabs
```

The `useResourceList` hook follows the backend's `meta.pagination.next` link,
so it drives **both** page- and cursor-paginated endpoints with no per-screen
paging code. Adding a new list screen = point `ResourceList` at a path and
provide a title/subtitle renderer.

## Run it

```bash
cd mobile
npm install
cp .env.example .env          # then edit EXPO_PUBLIC_API_BASE_URL
npm start                     # press i (iOS), a (Android), or scan in Expo Go
```

**Backend must be reachable from the device:**
- iOS simulator / web → `http://localhost:8000/api/v1` works.
- Physical phone (Expo Go) → set `EXPO_PUBLIC_API_BASE_URL` to your computer's
  LAN IP (e.g. `http://192.168.1.20:8000/api/v1`) **and** add that IP to Django
  `ALLOWED_HOSTS`. Run Django with `python manage.py runserver 0.0.0.0:8000`.

Log in with any BIMS user's credentials.

## How auth works

1. `POST /auth/login` → access + refresh tokens stored in SecureStore.
2. Every request carries `Authorization: Bearer <access>`.
3. On a `401`, the axios interceptor makes **one** `POST /auth/refresh`
   (concurrent 401s share it), stores the rotated tokens, and replays the
   request. If refresh fails, the session clears and the app returns to Login.
4. `Log out` calls `POST /auth/logout` to blacklist the refresh token
   (server-side per-device logout), then clears local tokens.

## Not built yet (next steps)

- Typed models per resource (currently rows are `__all__` records read via `pick`).
- Detail screens, create/edit forms (React Hook Form + Zod), master pickers.
- Offline queue + delta sync (`?updated_since=`), push notifications.
- Vector icons, app icon/splash assets.
