!!!!!!!!  this should be called from nos_grib2_launch.sh under /ush

        use grib_mod
       PARAMETER (kmax=99999999)
       PARAMETER (kfiles=17)


      integer           :: Lcgrib,Ryear,Rmonth,Rday,Rhour,Rmin,Rsec
      integer           :: Ifcsthr
      character (len=3) :: Area

      integer           :: Ierr,Lcsec2,Idefnum,Numcoord,Ipdsnum,Idrsnum
      integer           :: Ngrdpts,Ibmap,Dsf,Itemp

      integer,dimension(2)  :: Lsec0
      integer,dimension(13) :: Lsec1
      integer,dimension(5)  :: Igds
      integer,dimension(1)  :: Ideflist

      real, dimension(1)    :: Coordlist

      integer,dimension(:), allocatable :: Igdstmpl,Ipdstmpl,Idrstmpl
      real, dimension(:), allocatable   :: Fld
      real, dimension(:), allocatable   :: Fld2

      character (len=1),dimension(:),allocatable :: Cgrib


      character (len=1), dimension (1)  :: Csec2

      Logical*1       Bmap(1)
        
      character*120 OFS,OCEAN_MODEL*10,filename
        integer nhr0,nfile, nx,ny,ofsx,ofsy,nxnymax
        real wl



!      real, allocatable :: zeta  (:,:,:)


!        call read_ofs_variables_roms(ofs,yy,mm,dd,hh,zeta)

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!


!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

        NGDSTMPL=22

        IPDSTMPLEN=15
!        IPDSTMPLEN=32  !  machuan


        IDRSTMPLEN=16
!        Nx = 1073
!        Ny =689

!        Nx = 2145   ! 2.5km
!        Ny =1377

        Nx = 8577    ! 625m
        Ny = 5505    !  machuan did  

!        Res_con = 2539703
        Res_con = 634925


        Nxnymax= Nx * Ny
!        NGRIBM = 2958000
        NGRIBM = 29580000


        Ryear=2019
        Rmonth=3
        Rday=7
        Rhour=12
        Rmin=0
        Rsec=0

      OPEN(54,FILE='conus625m.grib2',FORM='UNFORMATTED')


      allocate (Igdstmpl(Ngdstmpl))
      allocate (Ipdstmpl(Ipdstmplen))
      allocate (Idrstmpl(Idrstmplen))
      allocate (Fld(Nxnymax))
      allocate (Fld2(Nxnymax))


      ALLOCATE (Cgrib(Ngribm))

C 10 = OCEANOGRAPHIC PRODUCT, 2 = EDITION NUMBER (GRIB2)
      LSEC0(1) = 10
      LSEC0(2) = 2
C 7 = NCEP, 14 = MDL, 4 VERSION, 1 = VERSION OF THE LOCAL TABLES.
      LSEC1(1) = 7
      LSEC1(2) = 14
      LSEC1(3) = 3
      LSEC1(4) = 1
C 1 = START OF FORECAST, RYEAR, RMONTH, RDAY, RHOUR, RMIN, RSEC
      LSEC1(5) = 1
      LSEC1(6) = RYEAR
      LSEC1(7) = RMONTH
      LSEC1(8) = RDAY
      LSEC1(9) = RHOUR
      LSEC1(10) = RMIN
      LSEC1(11) = RSEC
C 1 = OPERATIONAL TEST PRODUCT (0 WOULD BE OPERATIONAL)
      LSEC1(12) = 1
C 1 = FORECAST PRODUCTS
      LSEC1(13) = 1
      CALL GRIBCREATE(CGRIB,NGRIBM,LSEC0,LSEC1,IERR)
C CHECK THE RESULTS OF IERR.


        write(*,*) "=== mmgp after gribcreate ==="


      LCSEC2 = 0
      CALL ADDLOCAL(CGRIB,NGRIBM,CSEC2,LCSEC2,IERR)
C CHECK THE RESULTS OF IERR.

        write(*,*) "=== mmgp after addlocal ==="

C 0 = USING TEMPLATES, GRID SPECIFIED IN 3.1
      IGDS(1) = 0
      IGDS(2) = NX * NY
C 0 = MEANS NO IDEFLIST, 0 MEANS NO APPENDED LIST
      IGDS(3) = 0
      IGDS(4) = 0
C 30 = LAMBERT, 20 = POLAR STEREOGRAPHIC
!      IF(AREA=='con') THEN
        IGDS(5) = 30
!      ELSE IF(AREA=='ala') THEN
!        IGDS(5) = 20
!      END IF
      IGDSTMPL(1) = 1
      IGDSTMPL(2) = 0
      IGDSTMPL(3) = 6371200
      IGDSTMPL(4) = 0
      IGDSTMPL(5) = 0
      IGDSTMPL(6) = 0
      IGDSTMPL(7) = 0
      IGDSTMPL(8) = NX
      IGDSTMPL(9) = NY

        IGDSTMPL(10) = 20191999
        IGDSTMPL(11) = 238445999
      IGDSTMPL(12) = 0
        IGDSTMPL(13) = 25000000
        IGDSTMPL(14) = 265000000
        IGDSTMPL(15) = Res_con !2.5km
        IGDSTMPL(16) = Res_con !2.5km
        IGDSTMPL(17) = 0
        IGDSTMPL(18) = 64
        IGDSTMPL(19) = 25000000
        IGDSTMPL(20) = 25000000
        IGDSTMPL(21) = -90000000
        IGDSTMPL(22) = 0

      CALL ADDGRID(CGRIB,NGRIBM,IGDS,IGDSTMPL,NGDSTMPL,IDEFLIST,
     1             IDEFNUM,IERR)
C CHECK THE RESULTS OF IERR.

C 0 = FORECAST AT A HORIZONTAL LEVEL AT A POINT IN TIME
      IPDSNUM = 0
      IPDSTMPL(1) = 3
! PRODUCT NAME 193--ETSRG 250--ETCWL
!      IF(FLEEXT=='stormtide') THEN
!         IPDSTMPL(2) = 250
!      ELSEIF(FLEEXT=='stormsurge') THEN
!         IPDSTMPL(2) = 193
!      ELSE


!         IPDSTMPL(2) = 251  ! Tide only

!!!!  from 192-254 

         IPDSTMPL(2) = 193   ! :ELEV Ocean Surface Elevation Relative
 
!         IPDSTMPL(2) = 0  ! water temperature K






!      ENDIF
c 2 = FORECAST
      IPDSTMPL(3) = 2
      IPDSTMPL(4) = 0

!      IF(AREA=='con') THEN
!        IPDSTMPL(5) = 14
!      ELSE
!        IPDSTMPL(5) = 17
!      ENDIF
! ETSS processing ID 16
      IPDSTMPL(5) = 16
!
      IPDSTMPL(6) = 65535
      IPDSTMPL(7) = 255
      IPDSTMPL(8) = 1
      IPDSTMPL(9) = IFCSTHR
c 1 = GROUND OR WATER SURFACE
      IPDSTMPL(10) = 1
      IPDSTMPL(11) = 0
      IPDSTMPL(12) = 0
C -1 is all 1's if we are dealing with signed integers.
C 13, and 14 only need 1 byte of all 1's (missing), so could use 255
      IPDSTMPL(13) = -1
      IPDSTMPL(14) = -1
      IPDSTMPL(15) = -1
      NUMCOORD = 0
      NGRDPTS = NX * NY
      IDRSNUM = 2
C REFERENCE VALUE IS SET TO 9999 FOR
      IDRSTMPL(1) = 9999
      IDRSTMPL(2) = 0
C 5 = DECIMAL SCALE FACTOR
!      DSF = 5
      DSF = 3
      IDRSTMPL(3) = DSF
      IDRSTMPL(4) = 9999
C 0 = FLOATING POINT (ORIGINAL DATA WAS A FLOATING POINT NUMBER)
      IDRSTMPL(5) = 0
      IDRSTMPL(6) = 9999
C 1 = MISSING VALUE MANAGEMENT (PRIMARY ONLY)
      IDRSTMPL(7) = 1
      call mkieee(9999.,IDRSTMPL(8),1)
      call mkieee(9999.,IDRSTMPL(9),1)
      IDRSTMPL(10) = 9999
      IDRSTMPL(11) = 9999
      IDRSTMPL(12) = 9999
      IDRSTMPL(13) = 9999
      IDRSTMPL(14) = 9999
      IDRSTMPL(15) = 9999
      IDRSTMPL(16) = 9999

!!!!!!!!!!!!!!!!!!!  write all OFS to 625m grib2 grid


      DO 150 J=1,NY
        DO 140 I=1,NX
            FLD(I + (J - 1) * NX) = -99999.0
140    CONTINUE
 150  CONTINUE


        open (21,file="conus_cbofs_index_625m.out")

        km=0
        do k=1,kmax
        read (21,*,end=91) nx,ny,ofsx,ofsy
        km=km+1
        enddo
91      continue
         kcbofs=km
        close (21)

        open (21,file="conus_gomofs_index_625m.out")

        km=0
        do k=1,kmax
        read (21,*,end=92) nx,ny,ofsx,ofsy
        km=km+1
        enddo
92      continue
         kgomofs=km
        close (21)


        open (21,file="conus_ngofs_index_625m.out")

        km=0
        do k=1,kmax
        read (21,*,end=93) nx,ny,ofsx
        km=km+1
        enddo
93      continue
         kngofs=km
        close (21)

        open (21,file="conus_sfbofs_index_625m.out")

        km=0
        do k=1,kmax
        read (21,*,end=94) nx,ny,ofsx
        km=km+1
        enddo
94      continue
         ksfbofs=km
        close (21)



        open (31,file='conus_cbofs_zeta_value.out')
        open (32,file='conus_gomofs_zeta_value.out')
        open (33,file='conus_ngofs_zeta_value.out')
        open (34,file='conus_sfbofs_zeta_value.out')


        do k=1,kcbofs

                read(31,*) ofsx,ofsy,wl

        write(*,*) ofsx,ofsy,wl


                FLD(ofsx + (ofsy - 1) * NX) =wl 
        enddo

        do k=1,kgomofs
                read(32,*) ofsx,ofsy,wl
                FLD(ofsx + (ofsy - 1) * NX) =wl
        enddo

        do k=1,kngofs
                read(33,*) ofsx,ofsy,wl
                FLD(ofsx + (ofsy - 1) * NX) =wl
        enddo

        do k=1,ksfbofs
                read(34,*) ofsx,ofsy,wl
                FLD(ofsx + (ofsy - 1) * NX) =wl
        enddo

        



C NO BIT MAP APPLIES FOR THE DATA.
      IBMAP = 255
!      write(*,*)maxval(FLD)
      CALL ADDFIELD(CGRIB,NGRIBM,IPDSNUM,IPDSTMPL,IPDSTMPLEN,
     1              COORDLIST,NUMCOORD,IDRSNUM,IDRSTMPL,
     1              IDRSTMPLEN,FLD,NGRDPTS,IBMAP,BMAP,IERR)
      CALL GRIBEND(CGRIB,NGRIBM,LCGRIB,IERR)

        write(*,*) "==== LCGRIB IS ===", LCGRIB
        
!        lcgrib=992626
!        lcgrib=5902270

      WRITE(54) (CGRIB(K),K=1,LCGRIB)


C CHECK THE RESULTS OF IERR.

 


        write(*,*) "==== ha ha ha ha ==="

!     CALL W3TAGE('etss_out_grid')



        end


