# WCOSS2 appears to be a RedHat Enterprise Linux system. Therefore, we'll use RockyLinux since
# it claims to be a bug-for-bug replica of RHEL

# Versions of software to grab and build
ARG SLURM_VERSION=slurm-24-11-1-1
ARG ECFLOW_VERSION=5.6.0
ARG ADCIRC_VERSION=56.0.3
ARG SCHISM_VERSION=5.11.0
ARG GOSU_VERSION=1.17

# Environment configuration
#ARG ENVIRONMENT_PDY=20250401
#ARG ENVIRONMENT_CYC=00
#ARG ENVIRONMENT_WORKDIR=/home/wcoss2/sandbox

FROM rockylinux/rockylinux:9 AS builder

# Install all the libs we need to build the software we are interested in. When we build our final container,
# we will do the same thing, but remove the devel libs to save some space
#RUN dnf update -y && dnf install -y epel-release && \
#    dnf install -y --enablerepo=crb which gcc gcc-c++ gcc-gfortran make cmake git \
#                   openmpi openmpi-devel \
#                   boost-devel boost-system boost-filesystem boost-timer boost-date-time boost-program-options boost-chrono \
#                   netcdf netcdf-fortran netcdf-devel netcdf-fortran-devel \
#                   libtool ncurses-devel expat-devel openssl-devel python3-devel \
#                   automake expat-devel wget hostname zlib-devel  \
#                   jasper udunits2 nco ImageMagick proj proj-devel \
#                   bzip2 gnupg munge munge-devel psmisc bash-completion json-c http-parser \
#                   mysql mysql-server mysql-devel libjpeg-turbo libjpeg-turbo-devel
RUN dnf update -y && \
    dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm && \
    /usr/bin/crb enable && \
    dnf install -y --nobest which gcc gcc-c++ gcc-gfortran make cmake git \
                   openmpi openmpi-devel \
                   boost-devel boost-system boost-filesystem boost-timer boost-date-time boost-program-options boost-chrono \
                   netcdf netcdf-fortran netcdf-devel netcdf-fortran-devel \
                   libtool ncurses-devel expat-devel openssl-devel python3-devel \
                   automake expat-devel wget hostname zlib-devel  \
                   jasper udunits2 nco ImageMagick \
                   bzip2 gnupg munge munge-devel psmisc bash-completion json-c http-parser \
                   mysql mysql-server mysql-devel libjpeg-turbo libjpeg-turbo-devel && \
    dnf install -y https://download.fedoraproject.org/pub/epel/9/Everything/x86_64/Packages/p/proj-8.2.0-1.el9.x86_64.rpm \
                   https://download.fedoraproject.org/pub/epel/9/Everything/x86_64/Packages/p/proj-devel-8.2.0-1.el9.x86_64.rpm

# Install the python packages we'll be using. This just helps replicate the environment we use during the build
RUN pip install xarray pyyaml matplotlib cartopy netCDF4 pyshp more-itertools pytest pytz scikit-learn dateutils pyparsing \
                cftime termcolor shapely numpy pandas pluggy geopy attrs pyproj cython schema

# Install the SLURM job scheduler. WCOSS uses PBS, but PBS requires that we run using systemd. We have some more
# flexibility when using slurm, so this is going to have to be suitable enough for testing purposes
ARG SLURM_VERSION
RUN set -x \
    && git clone -b ${SLURM_VERSION} --single-branch --depth=1 https://github.com/SchedMD/slurm.git \
    && pushd slurm \
    && ./configure --prefix=/opt/slurm --sysconfdir=/opt/slurm/etc \
        --with-mysql_config=/usr/bin  --libdir=/opt/slurm/lib64 \
        --enable-cgroupv2=no \
    && make install \
    && install -D -m644 etc/cgroup.conf.example /opt/slurm/etc/cgroup.conf.example \
    && install -D -m644 etc/slurm.conf.example /opt/slurm/etc/slurm.conf.example \
    && install -D -m644 etc/slurmdbd.conf.example /opt/slurm/etc/slurmdbd.conf.example \
    && install -D -m644 contribs/slurm_completion_help/slurm_completion.sh /etc/profile.d/slurm_completion.sh \
    && popd \
    && rm -rf slurm \
    && groupadd -r --gid=990 slurm \
    && useradd -r -g slurm --uid=990 slurm \
    && mkdir /etc/sysconfig/slurm \
        /var/spool/slurmd \
        /var/run/slurmd \
        /var/run/slurmdbd \
        /var/lib/slurmd \
        /var/log/slurm \
        /data \
    && touch /var/lib/slurmd/node_state \
        /var/lib/slurmd/front_end_state \
        /var/lib/slurmd/job_state \
        /var/lib/slurmd/resv_state \
        /var/lib/slurmd/trigger_state \
        /var/lib/slurmd/assoc_mgr_state \
        /var/lib/slurmd/assoc_usage \
        /var/lib/slurmd/qos_usage \
        /var/lib/slurmd/fed_mgr_state \
    && chown -R slurm:slurm /var/*/slurm* \
    && chown -R munge:munge /run/munge \
    && chmod go-rw /run/munge \
    && /sbin/create-munge-key


# Build and install ECFLOW v5.13.7. This will get the source code and install it. ECFLOW is not available via
# pip (only conda), and this is a bit easier than trying to mix conda dependencies with our virtualized WCOSS2
ARG ECFLOW_VERSION
RUN mkdir ecflow_build && cd ecflow_build && \
    wget -O ecflow.tar.gz https://confluence.ecmwf.int/download/attachments/8650755/ecFlow-${ECFLOW_VERSION}-Source.tar.gz?api=v2 && \
    tar -xvf ecflow.tar.gz && rm ecflow.tar.gz && \
    mv ecFlow* ecflow && \
    cd ecflow && mkdir build && cd build && \
    cmake .. -DENABLE_UI=OFF \
        -DBoost_ROOT=/usr \
        -DENABLE_TESTS=OFF \
        -DENABLE_STATIC_BOOST_LIBS=OFF \
        -DCMAKE_INSTALL_PREFIX=/opt/ecflow && \
    make -j4 && make install

# Copy the fortran netcdf.mod into /usr/include so that cmake can find it
RUN cp /usr/lib64/gfortran/modules/netcdf.mod /usr/include/netcdf.mod


# Now, start installing the models that we need for testing
ARG ADCIRC_VERSION
RUN git clone --depth 1 --branch v${ADCIRC_VERSION} https://github.com/adcirc/adcirc && \
    mkdir adcirc_build && \
    cd adcirc_build && \
    export PATH=$PATH:/usr/lib64/openmpi/bin && \
    export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib64 && \
    cmake ../adcirc -DCMAKE_INSTALL_PREFIX=/opt/models/adcirc \
        -DENABLE_OUTPUT_NETCDF=ON \
        -DBUILD_ADCIRC=ON \
        -DBUILD_ADCPREP=ON \
        -DBUILD_PADCIRC=ON \
        -DNETCDFHOME=/usr \
        -DENABLE_GRIB2=ON \
        -DENABLE_DATETIME=ON && \
    make && make install

# RUN ln -s /usr/bin/python3 /usr/bin/python
RUN [ -e /usr/bin/python ] || ln -s /usr/bin/python3 /usr/bin/python
ARG SCHISM_VERSION
RUN git clone --depth 1 --branch v${SCHISM_VERSION} https://github.com/schism-dev/schism && \
    mkdir schism_build && \
    cd schism_build && \
    export PATH=$PATH:/usr/lib64/openmpi/bin && \
    export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib64 && \
    cmake ../schism/src -DCMAKE_INSTALL_PREFIX=/opt/models/schism -DBLD_STANDALONE=ON && \
    make && mkdir /opt/models/schism && mv bin /opt/models/schism/bin

COPY containers/slurm.conf /opt/slurm/etc/slurm.conf
COPY containers/cgroup.conf /opt/slurm/etc/cgroup.conf
COPY containers/slurmdbd.conf /opt/slurm/etc/slurmdbd.conf
COPY containers/get_slurm_node.py /opt/slurm/etc/get_slurm_node.py

# Enable CRB and update metadata
RUN dnf config-manager --set-enabled crb && dnf makecache

# Install Jasper (development + runtime)
RUN dnf install -y jasper jasper-devel

# Install PNG (development + runtime)
RUN dnf install -y libpng libpng-devel

# Install JPEG support (libjpeg-turbo)
RUN dnf install -y libjpeg-turbo libjpeg-turbo-devel

# Install BLAS/LAPACK
RUN dnf install -y blas-devel lapack-devel openblas-devel

# Optional: Install compression libs (if needed)
RUN dnf install -y zlib-devel bzip2-devel

# Clean to reduce image size
RUN dnf clean all

#RUN ln -sf /usr/lib64/libjasper.so.4 /usr/lib64/libjasper.so && \
#    ln -sf /usr/lib64/libpng16.so.16 /usr/lib64/libpng.so


# Build essential NCEP libraries (without IP library which requires BLAS/LAPACK)
# Build complete NCEP libraries (including IP library)
RUN set -x \
    # Build BACIO library
    && git clone --depth 1 https://github.com/NOAA-EMC/NCEPLIBS-bacio.git \
    && cd NCEPLIBS-bacio \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/ncep -DBUILD_TESTING=OFF \
    && make && make install \
    && cd / && rm -rf NCEPLIBS-bacio \
    \
    # Build W3EMC library
    && git clone --depth 1 https://github.com/NOAA-EMC/NCEPLIBS-w3emc.git \
    && cd NCEPLIBS-w3emc \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/ncep -DBUILD_TESTING=OFF -DCMAKE_PREFIX_PATH=/opt/ncep \
    && make && make install \
    && cd / && rm -rf NCEPLIBS-w3emc \
    \
    # Build W3NCO library
    && git clone --depth 1 https://github.com/NOAA-EMC/NCEPLIBS-w3nco.git \
    && cd NCEPLIBS-w3nco \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/ncep -DBUILD_TESTING=OFF -DCMAKE_PREFIX_PATH=/opt/ncep \
    && make && make install \
    && cd / && rm -rf NCEPLIBS-w3nco \
    \
    # Build prod_util (utilities and scripts)
    && git clone --depth 1 https://github.com/NOAA-EMC/NCEPLIBS-prod_util.git \
    && cd NCEPLIBS-prod_util \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/ncep -DBUILD_TESTING=OFF -DCMAKE_PREFIX_PATH=/opt/ncep \
    && make && make install \
    && cd / && rm -rf NCEPLIBS-prod_util \
    \
    # Build IP library (interpolation)
    && git clone --depth 1 https://github.com/NOAA-EMC/NCEPLIBS-ip.git \
    && cd NCEPLIBS-ip \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/ncep -DBUILD_TESTING=OFF -DCMAKE_PREFIX_PATH=/opt/ncep \
    && make && make install \
    && cd / && rm -rf NCEPLIBS-ip \
    \
    # Build G2C library
    && git clone --depth 1 https://github.com/NOAA-EMC/NCEPLIBS-g2c.git \
    && cd NCEPLIBS-g2c \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/ncep -DBUILD_TESTING=OFF -DCMAKE_PREFIX_PATH=/opt/ncep \
    && make && make install \
    && cd / && rm -rf NCEPLIBS-g2c \
    \
    # Build G2 library (GRIB2)
    && git clone --depth 1 https://github.com/NOAA-EMC/NCEPLIBS-g2.git \
    && cd NCEPLIBS-g2 \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/ncep -DBUILD_TESTING=OFF -DCMAKE_PREFIX_PATH=/opt/ncep \
    && make && make install \
    && cd / && rm -rf NCEPLIBS-g2 \
    \
    # Build BUFR library
    && git clone --depth 1 https://github.com/NOAA-EMC/NCEPLIBS-bufr.git \
    && cd NCEPLIBS-bufr \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/ncep -DBUILD_TESTING=OFF -DCMAKE_PREFIX_PATH=/opt/ncep \
    && make && make install \
    && cd / && rm -rf NCEPLIBS-bufr

# Build wgrib2
ARG WGRIB2_VERSION=2.0.8
RUN cd / && \
    wget https://www.ftp.cpc.ncep.noaa.gov/wd51we/wgrib2/wgrib2.tgz && \
    tar -xzf wgrib2.tgz && \
    cd grib2 && \
    export CC=gcc && \
    export FC=gfortran && \
    make && \
    mkdir -p /opt/wgrib2/bin && \
    cp wgrib2/wgrib2 /opt/wgrib2/bin/ && \
    cd / && \
    rm -rf wgrib2.tgz grib2


RUN mkdir -p /opt/stofs/exec

# Build STOFS 3D Atlantic utilities
COPY sorc /tmp/stofs_sorc

# Build stofs_3d_atl_tide_fac
RUN cd /tmp/stofs_sorc/stofs_3d_atl_tide_fac.fd && \
    make clean && \
    make && \
    cp -p stofs_3d_atl_tide_fac /opt/stofs/exec/ && \
    make clean

# Build stofs_3d_atl_netcdf2shef
RUN cd /tmp/stofs_sorc/stofs_3d_atl_netcdf2shef.fd && \
    make clean && \
    make && \
    cp -p stofs_3d_atl_netcdf2shef /opt/stofs/exec/ && \
    make clean

# Build stofs_3d_atl_gen_3Dth_from_hycom
RUN cd /tmp/stofs_sorc/stofs_3d_atl_gen_3Dth_from_hycom.fd && \
    export PATH=$PATH:/usr/lib64/openmpi/bin && \
    export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib64 && \
    make clean && \
    make && \
    cp -p stofs_3d_atl_gen_3Dth_from_hycom /opt/stofs/exec/ && \
    make clean

# Build stofs_3d_atl_gen_nudge_from_hycom
RUN cd /tmp/stofs_sorc/stofs_3d_atl_gen_nudge_from_hycom.fd && \
    export PATH=$PATH:/usr/lib64/openmpi/bin && \
    export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib64 && \
    make clean && \
    make && \
    cp -p stofs_3d_atl_gen_nudge_from_hycom /opt/stofs/exec/ && \
    make clean

# --------------------------
FROM rockylinux/rockylinux:9 AS wcoss2

RUN dnf update -y && \
    dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm && \
    /usr/bin/crb enable && \
    dnf install -y \
        which gcc gcc-c++ gcc-gfortran make cmake git \
        openmpi openmpi-devel boost-system boost-filesystem boost-timer boost-date-time boost-program-options boost-chrono boost-python3 \
        netcdf netcdf-fortran netcdf-devel netcdf-fortran-devel libtool python3-devel automake wget hostname \
        jasper udunits2 nco ImageMagick bzip2 gnupg munge munge-devel psmisc bash-completion json-c http-parser \
        mysql mysql-server mysql-libs environment-modules libjpeg-turbo emacs && \
    dnf install -y https://download.fedoraproject.org/pub/epel/9/Everything/x86_64/Packages/p/proj-8.2.0-1.el9.x86_64.rpm

RUN ln -sf /usr/lib64/libjasper.so.4 /usr/lib64/libjasper.so && \
    ln -sf /usr/lib64/libpng16.so.16 /usr/lib64/libpng.so


# Install the python packages we'll be using. This just helps replicate the environment we use during the build
RUN pip install xarray pyyaml matplotlib cartopy netCDF4 pyshp more-itertools pytest pytz scikit-learn dateutils pyparsing \
                cftime termcolor shapely numpy pandas pluggy geopy attrs pyproj cython schema

COPY --from=builder /opt/slurm /opt/slurm
COPY --from=builder /opt/ecflow /opt/ecflow
COPY --from=builder /opt/models/adcirc /opt/models/adcirc
COPY --from=builder /opt/models/schism /opt/models/schism
COPY --from=builder /opt/wgrib2 /opt/wgrib2
COPY --from=builder /opt/ncep /opt/ncep
COPY --from=builder /opt/wgrib2 /opt/wgrib2

RUN ln -s /opt/wgrib2/bin/wgrib2 /usr/local/bin/wgrib2

RUN chmod -R a+rx /opt/ncep/bin

# Install CFP replacement
COPY containers/install-cfp.sh /tmp/
RUN bash /tmp/install-cfp.sh && rm /tmp/install-cfp.sh

# Install MPI wrapper
COPY containers/install-mpi-wrapper.sh /tmp/
RUN bash /tmp/install-mpi-wrapper.sh && rm /tmp/install-mpi-wrapper.sh


ARG GOSU_VERSION
RUN set -ex \
    && wget -O /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/${GOSU_VERSION}/gosu-amd64" \
    && wget -O /usr/local/bin/gosu.asc "https://github.com/tianon/gosu/releases/download/${GOSU_VERSION}/gosu-amd64.asc" \
    && export GNUPGHOME="$(mktemp -d)" \
    && gpg --batch --keyserver hkps://keys.openpgp.org --recv-keys B42F6819007F00F88E364FD4036A9C25BF357DD4 \
    && gpg --batch --verify /usr/local/bin/gosu.asc /usr/local/bin/gosu \
    && rm -rf "${GNUPGHOME}" /usr/local/bin/gosu.asc \
    && chmod +x /usr/local/bin/gosu \
    && gosu nobody true

# Initialize the mysql database with one database called slurm_acct_db and a user called 'slurm' with password 'slurm'
RUN chown -R mysql:mysql /var/lib/mysql && \
    chown mysql:mysql /var/run/mysqld && \
    chown mysql:mysql /usr/libexec/mysqld && \
    /usr/libexec/mysqld --initialize-insecure --user=mysql --datadir=/var/lib/mysql

# Add the slurm user and create directories
RUN groupadd -r --gid=990 slurm \
    && useradd -r -g slurm --uid=990 slurm \
    && mkdir /etc/sysconfig/slurm \
        /var/spool/slurmd \
        /var/run/slurmd \
        /var/run/slurmdbd \
        /var/lib/slurmd \
        /var/log/slurm \
        /data \
    && touch /var/lib/slurmd/node_state \
        /var/lib/slurmd/front_end_state \
        /var/lib/slurmd/job_state \
        /var/lib/slurmd/resv_state \
        /var/lib/slurmd/trigger_state \
        /var/lib/slurmd/assoc_mgr_state \
        /var/lib/slurmd/assoc_usage \
        /var/lib/slurmd/qos_usage \
        /var/lib/slurmd/fed_mgr_state \
    && chown -R slurm:slurm /var/*/slurm* \
    && chown -R munge:munge /run/munge \
    && chown -R slurm:slurm /opt/slurm/etc \
    && chmod go-rwx /opt/slurm/etc/slurmdbd.conf \
    && chmod go-rw /run/munge \
    && /sbin/create-munge-key \
    && [ -e /usr/bin/python ] || ln -s /usr/bin/python3 /usr/bin/python

# Add the su password for the root user
RUN echo "root:root" | chpasswd

# Add sudo for wcoss2 user
RUN dnf install -y sudo && \
    echo "wcoss2 ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/wcoss2 && \
    chmod 0440 /etc/sudoers.d/wcoss2


# Generate the entrypoint script. This should:
# 1. Start munged (slurm's authentication)
# 2. Start the mysql server daemon
# 3. Start the slurm database daemon (slurmdbd)
# 4. Generate a slurm node file (since we don't know our hostname at build time, we generate dynamically at startup)
# 5. Place our hostname in slurm.conf as the primary controller for the system
# 6. Start the controller (slurmctld) and send the log into our logging folder
# 7. Start the compute node daemon (slurmd) and send the log to our logging folder
# 8. Start the ecflow server using port 3121
# 9. Add the wcoss2 user
# 10. Switch to the unpriviliged user (wcoss2) via gosu
RUN useradd -m wcoss2 && chown wcoss2:wcoss2 /home/wcoss2 && \
    # Setup .bashrc with color support and aliases
    echo '# Enable color support for ls and also add handy aliases' >> /home/wcoss2/.bashrc && \
    echo 'if [ -x /usr/bin/dircolors ]; then' >> /home/wcoss2/.bashrc && \
    echo '    eval "$(dircolors -b)"' >> /home/wcoss2/.bashrc && \
    echo '    alias ls="ls --color=auto"' >> /home/wcoss2/.bashrc && \
    echo '    alias dir="dir --color=auto"' >> /home/wcoss2/.bashrc && \
    echo '    alias vdir="vdir --color=auto"' >> /home/wcoss2/.bashrc && \
    echo '    alias grep="grep --color=auto"' >> /home/wcoss2/.bashrc && \
    echo '    alias fgrep="fgrep --color=auto"' >> /home/wcoss2/.bashrc && \
    echo '    alias egrep="egrep --color=auto"' >> /home/wcoss2/.bashrc && \
    echo 'fi' >> /home/wcoss2/.bashrc && \
    echo 'alias ll="ls -lt --color=auto"' >> /home/wcoss2/.bashrc && \
    chown wcoss2:wcoss2 /home/wcoss2/.bashrc && \
  { \
     echo '#!/usr/bin/bash' \
  && echo 'echo [INIT] Starting munge authentication daemon...' \
  && echo 'gosu munge /usr/sbin/munged' \
  && echo 'echo [INIT] Starting the mysql server daemon...' \
  && echo '/usr/libexec/mysqld --user mysql --datadir=/var/lib/mysql &' \
  && echo 'echo [INIT] Waiting for MySQL to start...' \
  && echo 'sleep 5' \
  && echo 'echo [INIT] Initializing MySQL database for SLURM...' \
  && echo 'mysql -u root -e "CREATE DATABASE IF NOT EXISTS slurm_acct_db"' \
  && echo 'mysql -u root -e "CREATE USER IF NOT EXISTS '\''slurm'\''@'\''localhost'\'' IDENTIFIED BY '\''slurm'\''"' \
  && echo 'mysql -u root -e "GRANT ALL PRIVILEGES ON slurm_acct_db.* TO '\''slurm'\''@'\''localhost'\''"' \
  && echo 'mysql -u root -e "FLUSH PRIVILEGES"' \
  && echo 'echo [INIT] Starting the SLURM database daemon...' \
  && echo 'gosu slurm /opt/slurm/sbin/slurmdbd' \
  && echo 'echo [INIT] Generating SLURM node configuration...' \
  && echo 'python3 /opt/slurm/etc/get_slurm_node.py' \
  && echo 'echo [INIT] Updating the slurm configuration file...' \
  && echo 'THISHOST=$(hostname) && perl -w -pi -e "s/<<HOSTNAME>>/$THISHOST/g" /opt/slurm/etc/slurm.conf' \
  && echo 'echo [INIT] Starting SLURM job controller daemon...' \
  && echo 'gosu slurm /opt/slurm/sbin/slurmctld' \
  && echo 'echo [INIT] Starting SLURM node daemon...' \
  && echo '/opt/slurm/sbin/slurmd' \
  && echo 'echo [INIT] Starting ecFlow server...' \
  && echo 'gosu wcoss2 bash -c log=$(/opt/ecflow/bin/ecflow_start.sh -p 3121 1>/home/wcoss2/ecflow.log 2>&1)' \
  && echo 'echo [INIT] Switching to user: wcoss2' \
  && echo 'exec gosu wcoss2 "$@"'; \
    } > /entrypoint.sh \
  && chmod a+x /entrypoint.sh


# Install the stofs workflow manager
RUN mkdir -p /home/wcoss2/stofs_workflow && mkdir -p /home/wcoss2/data
COPY src /home/wcoss2/stofs_workflow/src
COPY pyproject.toml /home/wcoss2/stofs_workflow/pyproject.toml
COPY examples/stofs_scripts /home/wcoss2/data/stofs_scripts
COPY examples/config_adcirc.yaml /home/wcoss2/config_adcirc.yaml
COPY examples/config_schism.yaml /home/wcoss2/config_schism.yaml
RUN pip install /home/wcoss2/stofs_workflow && \
    rm -rf /home/wcoss2/stofs_workflow && \
    chmod ugo+x /home/wcoss2/data/stofs_scripts/stofs_3d_atl/*

# Create required directory structure for scripts
RUN mkdir -p /home/wcoss2/sandbox/stofs3d/scripts/stofs_3d_atl \
    && mkdir -p /home/wcoss2/sandbox/stofs3d/ush/stofs_3d_atl \
    && mkdir -p /home/wcoss2/sandbox/stofs3d/ush/stofs_3d_atl/pysh \
    && mkdir -p /home/wcoss2/sandbox/stofs3d/fix/stofs_3d_atl \
    && mkdir -p /lfs/h1/ops/prod/com/nwm/v3.0 \
    && mkdir -p /lfs/h1/ops/prod/com/ \
    && mkdir -p /lfs/h1/ops/prod/dcom/ \
    && mkdir -p /home/wcoss2/sandbox/dcom_root \
    && mkdir -p /home/wcoss2/sandbox/stofs3d/exec/stofs_3d_atl \
    && mkdir -p /home/wcoss2/sandbox/stofs3d/dataroot/stofs_3d_atl_run_12_prod_v2.1/outputs


# Copy ush files
COPY ush/stofs_3d_atl/*.sh /home/wcoss2/sandbox/stofs3d/ush/stofs_3d_atl/
COPY ush/stofs_3d_atl/pysh/* /home/wcoss2/sandbox/stofs3d/ush/stofs_3d_atl/pysh



# Read and execute permission for user wcoss2
RUN chmod -R +x /home/wcoss2/sandbox/stofs3d/ush/stofs_3d_atl/
RUN chmod -R +x /lfs/h1/ops/prod/com/nwm/v3.0/
RUN chmod -R +x /lfs/h1/ops/prod/com/
RUN chmod -R +x /lfs/h1/ops/prod/dcom/
RUN chmod -R +x /lfs/h1/ops/prod/com/nwm/v3.0/
RUN chmod -R +x /home/wcoss2/sandbox/dcom_root/
RUN chmod -R +x /home/wcoss2/sandbox/stofs3d/dataroot/stofs_3d_atl_run_12_prod_v2.1
RUN chmod -R +x /home/wcoss2/sandbox/stofs3d/dataroot/stofs_3d_atl_run_12_prod_v2.1/outputs


# Copy pysh files
#COPY ush/stofs_3d_atl/pysh/* /home/wcoss2/sandbox/stofs3d/ush/stofs_3d_atl/pysh
RUN chmod -R +x /home/wcoss2/sandbox/stofs3d/ush/stofs_3d_atl/
RUN chmod -R +x /home/wcoss2/sandbox/stofs3d/ush/stofs_3d_atl/pysh

# Copy fix files
#COPY fix/stofs_3d_atl/* /home/wcoss2/sandbox/stofs3d/fix/stofs_3d_atl/

# Copy exec files
#COPY exec/stofs_3d_atl/* /home/wcoss2/sandbox/stofs3d/exec/stofs_3d_atl/
RUN chmod -R +x /home/wcoss2/sandbox/stofs3d/exec/stofs_3d_atl/

# Copy exec files
#COPY exec/stofs_3d_atl/* /home/wcoss2/sandbox/stofs3d/exec/stofs_3d_atl/
RUN chmod -R +x /home/wcoss2/sandbox/stofs3d/exec/stofs_3d_atl/

# Copy scripts to the expected locations
RUN cp -p /home/wcoss2/data/stofs_scripts/stofs_3d_atl/* /home/wcoss2/sandbox/stofs3d/scripts/stofs_3d_atl/ \
    && chmod -R +x /home/wcoss2/sandbox/stofs3d/scripts/stofs_3d_atl


# Generate the modulefiles
ARG ADCIRC_VERSION
ARG SCHISM_VERSION
ARG ECFLOW_VERSION
RUN mkdir -p /usr/share/modulefiles/models/adcirc && \
    mkdir -p /usr/share/modulefiles/models/schism && \
    mkdir -p /usr/share/modulefiles/ecflow && \
    mkdir -p /usr/share/modulefiles/slurm && \
    mkdir -p /usr/share/modulefiles/ncep && \
  {  echo '#%Module 1.0' \
  && echo '#' \
  && echo '#  ADCIRC module for use with environment-modules package:' \
  && echo '#' \
  && echo 'conflict		adcirc' \
  && echo 'module load mpi' \
  && echo 'prepend-path 		PATH 		/opt/models/adcirc/bin'; \
  } > /usr/share/modulefiles/models/adcirc/${ADCIRC_VERSION} \
  && {  echo '#%Module 1.0' \
  && echo '#' \
  && echo '#  SCHISM module for use with environment-modules package:' \
  && echo '#' \
  && echo 'conflict		schism' \
  && echo 'module load mpi' \
  && echo 'prepend-path 		PATH 		/opt/models/schism/bin'; \
  } > /usr/share/modulefiles/models/schism/${SCHISM_VERSION} \
  && {  echo '#%Module 1.0' \
  && echo '#' \
  && echo '#  ecFlow module for use with environment-modules package:' \
  && echo '#' \
  && echo 'conflict		ecflow' \
  && echo 'prepend-path 		PATH 		/opt/ecflow/bin' \
  && echo 'prepend-path 		LD_LIBRARY_PATH 		/opt/ecflow/lib' \
  && echo 'prepend-path     PYTHONPATH    /opt/ecflow/lib/python3.9/site-packages' \
  && echo 'setenv ECF_HOST localhost' \
  && echo 'setenv ECF_PORT 3121'; \
  } > /usr/share/modulefiles/ecflow/${ECFLOW_VERSION} \
  && {  echo '#%Module 1.0' \
  && echo '#' \
  && echo '#  slurm module for use with environment-modules package:' \
  && echo '#' \
  && echo 'conflict		slurm' \
  && echo 'prepend-path 		PATH 		/opt/slurm/bin'; \
  } > /usr/share/modulefiles/slurm/24.11.1.1 \
  && { echo '#%Module 1.0' \
  && echo '#' \
  && echo '#  Modulefile for NCEP libs' \
  && echo '#' \
  && echo 'conflict ncep' \
  && echo 'prepend-path PATH /opt/ncep/bin'; \
  } > /usr/share/modulefiles/ncep/develop \
  && { echo "module load slurm" \
  && echo "module load ecflow" \
  && echo "module load ncep"; \
  } >> /etc/environment-modules/initrc

# Set up the environment file
COPY containers/environment.sh /home/wcoss2/environment.sh
RUN chown wcoss2:wcoss2 /home/wcoss2/environment.sh && \
    mkdir -p /home/wcoss2/sandbox/date && \
    mkdir -p /home/wcoss2/sandbox/stofs3d/versions
COPY containers/run.ver /home/wcoss2/sandbox/stofs3d/versions/run.ver

# Set up the stofs-3d model data
#RUN mkdir -p /home/wcoss2/sandbox/stofs_3d/dataroot/fix && \
#    mkdir -p /home/wcoss2/sandbox/stofs_3d/dcom_root
#COPY examples/stofs3d /home/wcoss2/sandbox/stofs_3d/dataroot/fix
#RUN chown -R wcoss2:wcoss2 /home/wcoss2/sandbox

# Add the OpenMPI binaries to the system PATH
RUN echo 'export PATH=$PATH:/usr/lib64/openmpi/bin' >> /etc/bashrc && \
    echo 'export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/lib64/openmpi/lib' >> /etc/bashrc && \
    ln -sf /usr/lib64/openmpi/bin/mpiexec /usr/bin/mpiexec && \
    ln -sf /usr/lib64/openmpi/bin/mpirun /usr/bin/mpirun

# Dummy up the WCOSS paths
RUN mkdir -p /lfs/h1/gfs/v16.3 && \
    mkdir -p /lfs/h1/hrrr/v4.1 && \
    mkdir -p /lfs/h1/nwm/v3.0 && \
    mkdir -p /lfs/h1/rtofs/v2.4 && \
    mkdir -p /lfs/h1/ops/prod/config && \
    mkdir -p /lfs/h1/ops/prod/dcom && \
    mkdir -p /home/wcoss2/sandbox/date && \
    mkdir -p /home/wcoss2/sandbox/stofs3d/versions && \
    mkdir -p /home/wcoss2/sandbox/stofs3d/prev && \
    mkdir -p /home/wcoss2/sandbox/stofs3d/rerun && \
    mkdir -p /home/wcoss2/dcom_root && \
    mkdir -p /home/wcoss2/sandbox/stofs3d/dataroot/stofs_3d_atl_run_12_prod_v2.1/outputs && \
    chown -R wcoss2:wcoss2 /home/wcoss2/sandbox

COPY --from=builder /opt/stofs/exec/* /home/wcoss2/sandbox/stofs3d/exec/stofs_3d_atl/
COPY containers/sample_compaths.list /lfs/h1/ops/prod/config/compaths.list

ENTRYPOINT [ "/entrypoint.sh" ]
CMD [ "/usr/bin/bash" ]
WORKDIR /home/wcoss2
