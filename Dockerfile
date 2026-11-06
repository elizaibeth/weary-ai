FROM hugomods/hugo:0.160.1@sha256:cb4106ffd926692b2d0c62f768601f9323faddd4e4ee05d9d58ee0e08de77055 AS build
WORKDIR /site
COPY . .
RUN hugo --minify --gc --cleanDestinationDir

FROM caddy:2.10-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /site/public /srv
