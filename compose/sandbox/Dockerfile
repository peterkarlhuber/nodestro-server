# The sandbox daemon of the compose stack: Docker-in-Docker plus the AppArmor parser.
#
# On an AppArmor host the daemon reports AppArmor, and Nodestro's self-test then requires every tool container to
# run under an enforcing profile. The stock dind image has no apparmor_parser, so its daemon cannot load its
# docker-default profile and starts containers unconfined; the self-test refuses those. With the parser the daemon
# loads docker-default into the host kernel (the privileged container may) and confines its containers. On a host
# without AppArmor nothing changes.
FROM docker:29.9.2-dind
RUN apk add --no-cache apparmor
