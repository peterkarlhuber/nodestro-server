# The sandbox daemon of the compose stack: Docker-in-Docker that confines its containers with AppArmor.
#
# On an AppArmor host the daemon reports AppArmor, and Nodestro's self-test then requires every tool container to
# run under an enforcing profile. The stock dind image starts them unconfined: containerd treats the host as
# AppArmor-capable only when /sbin/apparmor_parser exists and the variable `container` is unset, and the image has
# no parser while its entrypoint exports container=docker. This image adds the parser (Alpine installs it under
# /usr/sbin, so it is linked to /sbin) and starts dockerd through a wrapper without `container`; the daemon then
# loads docker-default (the privileged container may) and confines its containers. On a host without AppArmor
# nothing changes.
# The base is pinned by its multi-arch index digest (the container is privileged), the package by its version.
FROM docker:29.9.2-dind@sha256:9e79b879b177fbd72c34376a3dd3d91747da5db49e1f560f76aea59561471977
RUN apk add --no-cache apparmor=4.1.7-r1 \
    && if [ ! -e /sbin/apparmor_parser ]; then ln -s "$(command -v apparmor_parser)" /sbin/apparmor_parser; fi \
    && /sbin/apparmor_parser --version
COPY --chmod=0755 dockerd /usr/local/sbin/dockerd
