       PARAMETER (kmax=99999999)
       PARAMETER (kfiles=17)


        include 'netcdf.inc'

        character*200 OFS, fn, conus_ofs_index_file, model

        integer kfiles,kk,nx,ny,ofsx,ofsy,ofsn,ofse        

        integer xi_rho,xi_u,xi_v,xi_psi,eta_rho,eta_u,
     %  eta_v,eta_psi,s_rho

        real, allocatable :: ofswl (:,:)
        real, allocatable :: ofsfvwl (:)
 


        read(5,'(a200)') OFS

!        deallocate (ofswl);
!        deallocate (ofsfvwl);


        if (trim(OFS)=='cbofs') then
        write(*,*) "==== mmgp ==="
        
        xi_rho = 332 ;
        xi_u = 331 ;
        xi_v = 332 ;
        xi_psi = 331 ;
        eta_rho = 291 ;
        eta_u = 291 ;
        eta_v = 290 ;
        eta_psi = 290 ;
        s_rho = 20 ;

        model="roms"
          allocate(ofswl(xi_rho,eta_rho))

        endif

        if (trim(OFS)=='gomofs') then

        xi_rho = 1173 ;
        xi_u = 1172 ;
        xi_v = 1173 ;
        xi_psi = 1172 ;
        eta_rho = 777 ;
        eta_u = 777 ;
        eta_v = 776 ;
        s_rho = 30 ;

        model="roms"
          allocate(ofswl(xi_rho,eta_rho))

        endif

        if (trim(OFS)=='ngofs') then

        nele = 174474 ;
        node = 90267 ;
        siglay = 40 ;
        siglev = 41 ;

        model="fvcom"
          allocate(ofsfvwl(node))


        endif

        if (trim(OFS)=='sfbofs') then

         nele = 102264 ;
        node = 54120 ;
        siglay = 20 ;
        siglev = 21 ;

        model="fvcom"
          allocate(ofsfvwl(node))


        endif





        conus_ofs_index_file="conus_"//trim(ofs)//"_index_625m.out"

        write(*,*) "==== the file ====",conus_ofs_index_file

        open(21,file=trim(conus_ofs_index_file))

        open(22,file="conus_"//trim(ofs)//"_zeta_value.out")



        km=0
        do k=1,kmax
        read (21,*,end=99) nx,ny,ofsx,ofsy
        km=km+1
        enddo 

99      continue                

        rewind 21

        write(*,*) "=== mmgp km ===",km



        do k=1,kfiles

                write(*,*) "===== kfiles ====",k

           read(5,'(a200)') fn
           write(*,'(a200)') fn

           STATUS=NF_OPEN(trim(fn),NF_NOWRITE,NCID)
           STATUS = NF_INQ_VARID(NCID,'zeta',IDVAR)

           if(model=="roms") then 
           STATUS = NF_GET_VAR_REAL(NCID,IDVAR,ofswl)
           else
           STATUS = NF_GET_VAR_REAL(NCID,IDVAR,ofsfvwl)
           endif


                if (model=="roms") then

                do kk=1,km
                        read (21,*) nx,ny,ofsx,ofsy
                        write(22,222) nx,ny,ofswl(ofsx,ofsy)
                enddo
               
                else


                do kk=1,km
                        read (21,*) nx,ny,ofsn
                        write(22,222) nx,ny,ofsfvwl(ofsn)
                enddo
                endif





        rewind 21


        enddo

222     format(2i12,f12.2)        
    




        end
