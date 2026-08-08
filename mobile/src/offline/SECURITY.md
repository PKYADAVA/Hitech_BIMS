# Offline data on the device

What is stored, where, and what actually protects it. Written down because the
honest answer is more limited than "the local database is encrypted", and a
reader who believes the stronger claim will make worse decisions.

## What is held on the handset

| Data | Where | Protection |
|---|---|---|
| JWT access + refresh tokens | Keychain (iOS) / Keystore (Android), via `expo-secure-store` | OS-level, hardware-backed where available |
| Passwords | **nowhere** — posted once at sign-in, never stored | — |
| Unsent transactions (`sync_queue`) | SQLite in the app's private data directory | App sandbox |
| Queued photos | App document directory | App sandbox |
| Read cache (registers opened offline) | AsyncStorage | App sandbox |

## What the sandbox does and does not give us

Android and iOS both keep an app's private directory unreadable by other
applications. That is real protection against a malicious app on the same
phone, and no protection at all against someone with the unlocked handset, a
rooted device, or a physical image of the storage.

`allowBackup` is off (`app.json`), so the queue and cache are not swept into
Google's cloud backup and restored onto a different phone.

## Encryption at rest — the gap

The queue is **not** encrypted at rest. `expo-sqlite` does not ship SQLCipher,
and `expo-crypto` offers hashing and randomness but not a cipher, so there is
no honest way to encrypt the database with what is in the SDK today. Options,
in the order they should be considered:

1. `op-sqlite` with SQLCipher, keyed from `expo-secure-store` — the real fix,
   and a native dependency change.
2. Encrypting only the `payload` column with a JS AES implementation — narrower
   and slower, and leaves the org columns and GPS in the clear.

Doing neither is a decision, not an oversight: the data at risk is one
supervisor's unsent round, the window is hours, and the device is company-
issued and screen-locked. Revisit if handsets start holding financial
transactions offline.

## On sign-out

The read cache is cleared, so the next person on a shared handset cannot open a
register and read the last one's farms.

The queue is deliberately **not** cleared. An entry filed with no signal exists
nowhere else, and a supervisor ending their shift before reaching signal must
not lose the round. Each entry records whose it is and is only sent while that
user is signed in — so it is invisible to, and unsendable by, anyone else.
