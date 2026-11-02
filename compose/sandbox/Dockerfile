# The sandbox daemon of the compose stack: Docker-in-Docker plus the AppArmor parser.
#
# On an AppArmor host the daemon reports AppArmor, and Nodestro's self-test then requires every tool container to
# run under an enforcing profile. The stock dind image has no apparmor_parser, so its daemon cannot load its
# docker-default profile and starts containers unconfined; the self-test refuses those. With the parser the daemon
# loads docker-default into the host kernel (the privileged container may) and confines its containers. On a host
# without AppArmor nothing changes.
#
# containerd decides "the host supports AppArmor" only when /sbin/apparmor_parser exists (and the variable
# `container` is unset), while `docker info` reports AppArmor without it. Alpine installs the parser under
# /usr/sbin, so it is linked to /sbin; the build fails if neither is there.
FROM docker:29.9.2-dind
RUN apk add --no-cache apparmor \
    && if [ ! -e /sbin/apparmor_parser ]; then ln -s "$(command -v apparmor_parser)" /sbin/apparmor_parser; fi \
    && /sbin/apparmor_parser --version
