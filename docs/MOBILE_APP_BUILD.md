# Mobile App Build & Deployment

All commands run from `src/balanceai_frontend/`.

## Pre-build checks

Catch dependency issues before a native build fails.

```bash
npx expo install --check
npx expo-doctor
rm -rf node_modules && npm ci
```

## Local dev

Run the app on your machine.

```bash
npm install
npx expo start --ios
npx expo start --android
```

## Build

Produce installable app builds via EAS.

```bash
npx eas-cli build --platform android --profile preview
npx eas-cli build --platform ios --profile preview
```

## Status

Check progress and results of past builds.

```bash
npx eas-cli build:list --limit 5
npx eas-cli build:view <build-id>
```

## Submit

Upload a finished build to the app stores.

```bash
npx eas-cli submit --platform ios
npx eas-cli submit --platform android
```
