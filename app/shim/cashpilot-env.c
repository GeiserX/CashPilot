/*
 * cashpilot-env: start an earner with credentials Docker never records.
 *
 * The worker (app/secret_env.py) creates the earner with this program as its
 * entrypoint and the earner's real entrypoint and command as its arguments.
 * Before the start it writes the secret variables into a volume at
 * /run/cashpilot-secret/env, as NAME=value records separated by NUL bytes.
 *
 * This program reads that file, sets each variable, replaces each ${NAME} of
 * those variables in its arguments with the value (the catalog puts some
 * passwords on the command line), and execs the arguments. Nothing else: no
 * shell, no other expansion, no libc beyond what a static musl build carries,
 * so it runs in any image, a scratch or distroless one included.
 *
 * Exit codes: 127 when the program cannot be run, 126 when the secret file is
 * missing or unreadable. A missing file stops the earner rather than start it
 * without its login.
 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef ENV_FILE
#define ENV_FILE "/run/cashpilot-secret/env"
#endif
#define MAX_FILE (1 << 20)

static char *names[256];
static char *values[256];
static int count;

static void die(int code, const char *what, const char *detail) {
    fprintf(stderr, "cashpilot-env: %s%s%s\n", what, detail ? ": " : "", detail ? detail : "");
    exit(code);
}

static char *read_file(size_t *len) {
    int fd = open(ENV_FILE, O_RDONLY | O_CLOEXEC);
    if (fd < 0) die(126, "cannot open " ENV_FILE, strerror(errno));
    char *buf = malloc(MAX_FILE + 1);
    if (!buf) die(126, "out of memory", NULL);
    size_t got = 0;
    for (;;) {
        ssize_t n = read(fd, buf + got, MAX_FILE - got);
        if (n < 0) {
            if (errno == EINTR) continue;
            die(126, "cannot read " ENV_FILE, strerror(errno));
        }
        if (n == 0) break;
        got += (size_t)n;
        if (got == MAX_FILE) die(126, ENV_FILE " is too large", NULL);
    }
    close(fd);
    buf[got] = '\0';
    *len = got;
    return buf;
}

/* ${NAME} -> value for the names in the file; anything else stays as written. */
static char *expand(const char *arg) {
    size_t cap = strlen(arg) + 1, used = 0;
    char *out = malloc(cap);
    if (!out) die(127, "out of memory", NULL);
    const char *p = arg;
    while (*p) {
        const char *val = NULL;
        size_t skip = 0;
        if (p[0] == '$' && p[1] == '{') {
            const char *end = strchr(p + 2, '}');
            if (end) {
                size_t nlen = (size_t)(end - (p + 2));
                for (int i = 0; i < count; i++) {
                    if (strlen(names[i]) == nlen && strncmp(names[i], p + 2, nlen) == 0) {
                        val = values[i];
                        skip = nlen + 3;
                        break;
                    }
                }
            }
        }
        const char *piece = val ? val : p;
        size_t plen = val ? strlen(val) : 1;
        if (used + plen + 1 > cap) {
            cap = (used + plen + 1) * 2;
            out = realloc(out, cap);
            if (!out) die(127, "out of memory", NULL);
        }
        memcpy(out + used, piece, plen);
        used += plen;
        p += val ? skip : 1;
    }
    out[used] = '\0';
    return out;
}

int main(int argc, char **argv) {
    if (argc < 2) die(127, "no program to run", NULL);
    size_t len = 0;
    char *buf = read_file(&len);
    for (size_t at = 0; at < len;) {
        char *rec = buf + at;
        size_t rlen = strlen(rec);
        at += rlen + 1;
        if (!rlen) continue;
        char *eq = strchr(rec, '=');
        if (!eq || eq == rec) die(126, ENV_FILE " holds a record without a name", NULL);
        if (count == (int)(sizeof(names) / sizeof(names[0]))) die(126, ENV_FILE " holds too many variables", NULL);
        *eq = '\0';
        names[count] = rec;
        values[count] = eq + 1;
        count++;
        if (setenv(rec, eq + 1, 1) != 0) die(126, "cannot set a variable", strerror(errno));
    }
    char **args = calloc((size_t)argc, sizeof(char *));
    if (!args) die(127, "out of memory", NULL);
    for (int i = 1; i < argc; i++) args[i - 1] = expand(argv[i]);
    execvp(args[0], args);
    die(127, args[0], strerror(errno));
    return 127;
}
