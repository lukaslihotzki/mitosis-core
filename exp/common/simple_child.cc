#include <assert.h>
#include <gflags/gflags.h>
#include <unistd.h>
#include "../../mitosis-user-libs/mitosis-c-client//include/syscall.h"

DEFINE_int64(mac_id, 1, "machine id");
DEFINE_int64(handler_id, 73, "rfork handler id");

int
main(int argc, char *argv[]) {
    gflags::ParseCommandLineFlags(&argc, &argv, true);

    int sd = sopen();
    printf("mac id:%d\n", FLAGS_mac_id);
    assert(sd != 0);
    sleep(1);

    fork_resume_remote(sd, FLAGS_mac_id, FLAGS_handler_id);
    assert(false);
    return 0;
}