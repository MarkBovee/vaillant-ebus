# FAQ

## Does this require cloud access?

No.

## Does this require extra hardware?

No, only the VR921 gateway already connected to the heat pump.

## Why do some scopes have descriptions but no values?

VR921 exposes more measurement definitions than it currently returns through the tested path. Poll fallback is implemented, but some values still do not arrive.

## What is the daemon for?

It keeps one trusted EEBUS session alive during development and exposes cached state over local HTTP.
