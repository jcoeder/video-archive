{pkgs}: {
  deps = [
    pkgs.libGLU
    pkgs.libGL
    pkgs.ffmpeg
    pkgs.postgresql
    pkgs.openssl
  ];
}
