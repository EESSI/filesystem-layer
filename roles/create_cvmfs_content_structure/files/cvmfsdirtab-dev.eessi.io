# Software layer paths
# CPU targets: /<project name>/versions/<version>/software/{linux,macos}/{aarch64,riscv64,x86_64}/<vendor>/<microarchitecture>/software
/*/versions/*/software/*/*/*/*/software
/*/versions/*/software/*/*/*/*/software/*/*
/*/versions/*/software/*/*/*/*/modules
/*/versions/*/software/*/*/*/*/reprod
# Accelerator targets: /<project name>/versions/<version>/software/{linux,macos}/{aarch64,riscv64,x86_64}/<vendor>/<microarchitecture>/accel/<vendor>/<type>/software
/*/versions/*/software/*/*/*/*/accel/*/*/software
/*/versions/*/software/*/*/*/*/accel/*/*/software/*/*
/*/versions/*/software/*/*/*/*/accel/*/*/modules
/*/versions/*/software/*/*/*/*/accel/*/*/reprod
# generic and some (aarch64) targets are one level less deep (no <vendor>)
/*/versions/*/software/*/*/*/software
/*/versions/*/software/*/*/*/software/*/*
/*/versions/*/software/*/*/*/modules
/*/versions/*/software/*/*/*/reprod
/*/versions/*/software/*/*/*/accel/*/*/software
/*/versions/*/software/*/*/*/accel/*/*/software/*/*
/*/versions/*/software/*/*/*/accel/*/*/modules
/*/versions/*/software/*/*/*/accel/*/*/reprod
