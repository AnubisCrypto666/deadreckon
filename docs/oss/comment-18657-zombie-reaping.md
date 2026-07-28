# Comment to post on datahub-project/datahub#18657

Confirming this on a completely different platform, with numbers that
line up with yours.

**macOS 15.6.1 / arm64, Docker Desktop (Engine 29.6.2)**, quickstart
`v1.5.0.6`, `opensearchproject/opensearch:2.19.3`, 8 CPUs, 9.7 GB
allocated to Docker.

Measured inside `datahub-opensearch-1` after **90 minutes** of uptime:

| | |
|---|---|
| Processes in container | 1062 |
| …of which zombies | **1060** |
| Real JVM threads (`/proc/1/task`) | **140** |
| Rate | **708/hour** (vs the 720/hour a 5s interval predicts) |
| `OOMKilled` | `false` |

Same crash signature as yours when it did die, down to the stack size:

```
[warning][os,thread] Failed to start thread "Unknown thread" - pthread_create failed (EAGAIN)
                     for attributes: stacksize: 1024k, guardsize: 4k, detached.
java.lang.OutOfMemoryError: unable to create native thread: possibly out of memory
        or process/resource limits reached
```

Your isolation of the variable — `datahub-gms` running a *more* aggressive
1s curl healthcheck without leaking, because its PID 1 reaps — is what
convinced me. I had initially misdiagnosed this on my own instance as
thread-stack memory pressure, and the reason the wrong theory looked
plausible is worth flagging for anyone else who lands here: counting
"threads" with `ls /proc/*/task | wc -l` walks the task directory of
*every* process in the container, so with thousands of zombies present it
returns a number (3042, in my case) that looks exactly like runaway thread
creation. `ls /proc/1/task | wc -l` gives the JVM's actual 140.

**One platform difference that affects time-to-crash.** On Docker Desktop
my `pids.max` reads `max` rather than a concrete cgroup limit:

```
$ cat /sys/fs/cgroup/pids.current   ->  1202
$ cat /sys/fs/cgroup/pids.max       ->  max
```

So the binding limit here isn't the container's cgroup PID ceiling the way
it is in your 18864-slot case — it lands somewhere further out (kernel
`pid_max`/`threads-max` in the LinuxKit VM). The leak rate is identical,
but the interval between crashes will vary by platform, which may explain
different "about once a day" numbers if others report them. Doesn't change
the diagnosis or the fix.

`init: true` on the service is the right fix as far as I can tell. I've
verified the overlay merges cleanly onto the generated quickstart file
without disturbing the image, healthcheck, JVM options or volumes:

```bash
docker compose --profile quickstart \
  -f ~/.datahub/quickstart/docker-compose.yml \
  -f docker-compose.opensearch-init.yml config
```

Worth noting for anyone applying it by hand: editing
`~/.datahub/quickstart/docker-compose.yml` in place does not survive,
because `datahub docker quickstart` rewrites that file on every run unless
you pass `-f` (`download_compose_files` opens it `"wb"`). Passing `-f`
both skips the re-download and lets you layer an overlay, so that's the
route that sticks.

Unrelated side note, since it came up while measuring the above and it's
adjacent rather than part of this bug: with the showcase datapack loaded,
the six quickstart containers idle at ~4.23 GiB combined (≈4.54 GB), which
is already above `MIN_MEMORY_NEEDED = 4.3` GB in
[`docker_check.py`](https://github.com/datahub-project/datahub/blob/1703684/metadata-ingestion/src/datahub/cli/docker_check.py)
before any indexing work. I haven't tested whether the stack actually
fails *at* a 4.3 GB allocation, so I'm mentioning it rather than claiming
it — happy to file separately if it's useful.
