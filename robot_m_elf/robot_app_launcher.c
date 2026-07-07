#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    const char *terminal = "/usr/bin/gnome-terminal";
    const char *launcher = "/home/elf/Desktop/robot_m/start_robot_app.sh";

    execl(terminal, "gnome-terminal", "--", launcher, (char *)NULL);

    fprintf(stderr, "启动终端失败: %s\n", strerror(errno));
    return 1;
}
