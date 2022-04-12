#define _GNU_SOURCE
#include <sched.h>
#include <stddef.h>
#include <stdio.h>
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <string.h>

#include "lean_container.h"

#define BUF_SIZE 256
#define DEFAULT_PERMISSION S_IRWXU|S_IRGRP|S_IXGRP|S_IROTH|S_IXOTH

// TODO: dynamicly assign these values
#define DEFAULT_NUMA_COUNT 2
#define DEFAULT_CPU_COUNT 48

char* cgroup_directory_prefix[] = {
    "/sys/fs/cgroup/hugetlb/mitosis/%s",
    "/sys/fs/cgroup/perf_event/mitosis/%s",
    "/sys/fs/cgroup/net_cls,net_prio/mitosis/%s",
    "/sys/fs/cgroup/pids/mitosis/%s",
    "/sys/fs/cgroup/devices/mitosis/%s",
    "/sys/fs/cgroup/freezer/mitosis/%s",
    "/sys/fs/cgroup/cpu,cpuacct/mitosis/%s",
    "/sys/fs/cgroup/cpuset/mitosis/%s",
    "/sys/fs/cgroup/blkio/mitosis/%s",
    "/sys/fs/cgroup/memory/mitosis/%s",
    "/sys/fs/cgroup/systemd/mitosis/%s",
    NULL,
};

char* cpuset_cgroup_directory_prefix = "/sys/fs/cgroup/cpuset/mitosis/%s";
char* memory_cgroup_directory_prefix = "/sys/fs/cgroup/memory/mitosis/%s";
char* freezer_cgroup_directory_prefix = "/sys/fs/cgroup/freezer/mitosis/%s";

// ============================== begin utility functions ==============================

// writing pid to cgroup.procs under the cgroup directory will add the process to a cgroup
void cgroup_file_name(char* buf, const char* prefix, const char* name) {
    char path_buf[BUF_SIZE];
    sprintf(path_buf, prefix, name);
    sprintf(buf, "%s%s", path_buf, "/cgroup.procs");
}

// a wrapper to write pid to cgroupfs
int write_pid(pid_t pid, const char* cgroupfs_path) {
    char buf[BUF_SIZE];
    sprintf(buf, "%d", pid);
    size_t len = strlen(buf);
    
    int fd = open(cgroupfs_path, O_WRONLY);
    if (fd < 0) {
        perror("open");
        return -1;
    }

    ssize_t ret = write(fd, buf, len);
    if (ret != len) {
        fprintf(stderr, "write pid %s to %s returns %ld, expected %ld\n", buf, cgroupfs_path, ret, len);
        close(fd);
        return -1;
    }

    close(fd);
    return 0;
}

// allow the process to run on numa node(s)
int set_numa_cpuset(char* cpuset_root, int numa_count) {
    char path_buf[BUF_SIZE];
    sprintf(path_buf, "%s%s", cpuset_root, "/cpuset.mems");
    
    // the following code does these things:
    // echo 0-0 > /sys/fs/cgroup/.../cpuset.mems # process is allowed to run on numa node 0
    // echo 0-1 > /sys/fs/cgroup/.../cpuset.mems # process is allowed to run on numa node 0 and 1
    int fd = open(path_buf, O_WRONLY);
    if (fd < 0) {
        perror("open");
        return -1;
    }

    // TODO: how to choose the numa node?
    // TODO: error handling
    char numa_buf[BUF_SIZE];
    sprintf(numa_buf, "0-%d", numa_count-1);
    size_t len = strlen(numa_buf);
    ssize_t ret = write(fd, numa_buf, len);
    if (ret != len) {
        fprintf(stderr, "write numa id %s to %s returns %ld, expected %ld\n", numa_buf, path_buf, ret, len);
        close(fd);
        return -1;
    }

    close(fd);
    return 0;
}

// allow the process to run on cpu(s)
int set_cpu_number_cpuset(char* cpuset_root, int cpu_count) {
    char path_buf[BUF_SIZE];
    sprintf(path_buf, "%s%s", cpuset_root, "/cpuset.cpus");

    // the following code does these things:
    // echo 0-0 > /sys/fs/cgroup/.../cpuset.cpus # process is allowed to run on cpu 0
    // echo 0-1 > /sys/fs/cgroup/.../cpuset.cpus # process is allowed to run on cpu 0 and 1
    int fd = open(path_buf, O_WRONLY);
    if (fd < 0) {
        perror("open");
        return -1;
    }

    // TODO: how to choose the cpu?
    // TODO: error handling
    char cpuset_buf[BUF_SIZE];
    sprintf(cpuset_buf, "0-%d", cpu_count-1);
    size_t len = strlen(cpuset_buf);
    ssize_t ret = write(fd, cpuset_buf, len);
    if (ret != len) {
        fprintf(stderr, "write cpu id %s to %s returns %ld, expected %ld\n", cpuset_buf, path_buf, ret, len);
        close(fd);
        return -1;
    }

    close(fd);
    return 0;
}

// set the root cpuset, allocate all the resources
int set_mitosis_root_cpuset() {
    int ret;
    char mitosis_root_cpuset_path[BUF_SIZE];
    sprintf(mitosis_root_cpuset_path, cpuset_cgroup_directory_prefix, "");

    ret = set_numa_cpuset(mitosis_root_cpuset_path, DEFAULT_NUMA_COUNT);
    if (ret < 0)
        return ret;
    
    ret = set_cpu_number_cpuset(mitosis_root_cpuset_path, DEFAULT_CPU_COUNT);
    if (ret < 0)
        return ret;
    
    return 0;
}

// set cpuset parameters (cpu count and numa node count)
int set_cpuset_cgroup(char* name, int cpu_count, int numa_count) {
    char cpuset_root[BUF_SIZE];
    int ret;
    sprintf(cpuset_root, cpuset_cgroup_directory_prefix, name);

    if (cpu_count <= 0) {
        cpu_count = DEFAULT_CPU_COUNT;
    }

    if (numa_count <= 0) {
        numa_count = DEFAULT_NUMA_COUNT;
    }

    ret = set_cpu_number_cpuset(cpuset_root, cpu_count);
    if (ret < 0)
        return ret;
    
    ret = set_numa_cpuset(cpuset_root, numa_count);
    if (ret < 0)
        return ret;

    return 0;
}

// a wrapper to write the memory parameter the memory cgroupfs
int write_memory_limit(char* memory_cgroup_root, long memory_in_bytes) {
    char buf[BUF_SIZE];
    char path_buf[BUF_SIZE];
    size_t len;

    sprintf(buf, "%ld", memory_in_bytes);
    len = strlen(buf);

    sprintf(path_buf, "%s%s", memory_cgroup_root, "/memory.limit_in_bytes");

    // the following code does these things:
    // echo 134217728 > /sys/fs/cgroup/.../memory.limit_in_bytes # process is allowed to use 128MB memory
    int fd = open(path_buf, O_WRONLY);
    if (fd < 0) {
        perror("open");
        return -1;
    }

    ssize_t ret = write(fd, buf, len);
    if (ret != len) {
        fprintf(stderr, "write memory limit %s to %s returns %ld, expected %ld\n", buf, path_buf, ret, len);
        close(fd);
        return -1;
    }

    close(fd);
    return 0;
    
}

// set the memory paramter for the corresponding container template
int set_memory_cgroup(char* name, long memory_in_mb) {
    if (memory_in_mb <= 0) {
        // the default memory setting is the whole available memory
        return 0;
    }

    char memory_cgroup_path[BUF_SIZE];
    sprintf(memory_cgroup_path, memory_cgroup_directory_prefix, name);

    long memory_in_bytes = memory_in_mb * 1024 * 1024;
    return write_memory_limit(memory_cgroup_path, memory_in_bytes);
}

// ============================== end utility functions ==============================

int init_cgroup() {
    int ret;
    char buf[BUF_SIZE];
    for (char** cgroup = cgroup_directory_prefix; *cgroup != NULL; cgroup++) {
        sprintf(buf, *cgroup, "");
        ret = mkdir(buf, DEFAULT_PERMISSION);
        if (ret < 0 && errno != EEXIST) {
            perror("mkdir");
            return -1;
        }
    }
    set_mitosis_root_cpuset();
    return 0;
}

int deinit_cgroup() {
    int ret;
    char buf[BUF_SIZE];
    for (char** cgroup = cgroup_directory_prefix; *cgroup != NULL; cgroup++) {
        sprintf(buf, *cgroup, "");
        ret = rmdir(buf);
        if (ret < 0 && errno != ENOENT) {
            perror("rmdir");
            return -1;
        }
    }
    return 0;
}

int add_lean_container_template(char* name, struct ContainerSpec* spec) {
    char buf[BUF_SIZE];
    int ret;

    for (char** cgroup = cgroup_directory_prefix; *cgroup != NULL; cgroup++) {
        sprintf(buf, *cgroup, name);
        ret = mkdir(buf, DEFAULT_PERMISSION);
        if (ret < 0 && errno != EEXIST) {
            perror("mkdir");
            return -1;
        }
    }

    set_cpuset_cgroup(name, spec->cpu_count, spec->numa_count);
    set_memory_cgroup(name, spec->memory_in_mb);
    return 0;
}

int remove_lean_container_template(char* name) {
    char buf[BUF_SIZE];
    int ret;
    for (char** cgroup = cgroup_directory_prefix; *cgroup != NULL; cgroup++) {
        sprintf(buf, *cgroup, name);
        ret = rmdir(buf);
        if (ret < 0 && errno != ENOENT) {
            perror("rmdir: ");
            return -1;
        }
    }
    return 0;
}

int setup_lean_container(char* name, char* rootfs_path) {
    int ret;
    int pipefd[2];
    pid_t pid;

    if (pipe(pipefd) < 0) {
        perror("pipe");
        return -1;
    }

    if (unshare(CLONE_NEWUTS | CLONE_NEWPID | CLONE_NEWIPC | CLONE_NEWNS) < 0) {
        perror("unshare");
        goto err;
    }

    pid = fork();
    if (pid < 0) {
        perror("fork");
        goto err;
    }

    if (pid) {
        // parent process
        // write the child pid to the cgroupfs
        char sign = 'a';
        char path_buf[BUF_SIZE];
        for (char** cgroup = cgroup_directory_prefix; *cgroup != NULL; cgroup++) {
            cgroup_file_name(path_buf, *cgroup, name);
            ret = write_pid(pid, path_buf);
            if (ret < 0) {
                goto err;
            }
        }
        
        // write a sign to the pipe fd to inform the child process to run
        // the child process must not run before the cgroup has been setup
        write(pipefd[1], &sign, sizeof(sign));
        close(pipefd[0]);
        close(pipefd[1]);
        return pid;
    } else {
        // child process must wait for the parent to setup cgroup
        char sign;
        int ret;

        // we first change directory to the target path and then chroot to "."
        ret = chdir(rootfs_path);
        if (ret != 0) {
            fprintf(stderr, "chdir to %s failed\n", rootfs_path);
            goto err;
        }

        ret = chroot(".");
        if (ret != 0) {
            fprintf(stderr, "chroot failed\n");
            goto err;
        }

        read(pipefd[0], &sign, sizeof(sign));
        close(pipefd[0]);
        close(pipefd[1]);
        return 0;
    }

err:
    close(pipefd[0]);
    close(pipefd[1]);
    return -1;
}

int pause_container(char* name) {
    char buf[BUF_SIZE];
    char freezer_state[BUF_SIZE];
    char* frozen = "FROZEN";
    size_t len = strlen(frozen);

    sprintf(buf, freezer_cgroup_directory_prefix, name);
    sprintf(freezer_state, "%s%s", buf, "/freezer.state");

    int fd = open(freezer_state, O_WRONLY);
    if (fd < 0) {
        perror("open");
        return -1;
    }

    // freeze the container
    ssize_t ret = write(fd, frozen, len);
    if (ret != len) {
        fprintf(stderr, "fail to write %s to %s: return %ld, expected %ld\n", frozen, freezer_state, ret, len);
        close(fd);
        return -1;
    }

    close(fd);
    return 0;
}

int unpause_container(char* name) {
    char buf[BUF_SIZE];
    char freezer_state[BUF_SIZE];
    char* thawed = "THAWED";
    size_t len = strlen(thawed);

    sprintf(buf, freezer_cgroup_directory_prefix, name);
    sprintf(freezer_state, "%s%s", buf, "/freezer.state");

    int fd = open(freezer_state, O_WRONLY);
    if (fd < 0) {
        perror("open");
        return -1;
    }

    // unfreeze the container
    ssize_t ret = write(fd, thawed, len);
    if (ret != len) {
        fprintf(stderr, "fail to write %s to %s: return %ld, expected %ld\n", thawed, freezer_state, ret, len);
        close(fd);
        return -1;
    }

    close(fd);
    return 0;
}
