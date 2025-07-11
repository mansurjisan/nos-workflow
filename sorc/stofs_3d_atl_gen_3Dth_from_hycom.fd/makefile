#FC=${COMP_F} #WCOSS2
FC=gfortran
OPT= -O2 -fbounds-check -fbacktrace
LIB= -I/usr/lib64/gfortran/modules -I/usr/include -L/usr/lib64 -lnetcdf -lnetcdff






all: compute_zcor.mod extract_mod.mod pt_in_poly_test.mod schism_geometry_mod.mod
	$(FC) $(OPT) -o stofs_3d_atl_gen_3Dth_from_hycom stofs_3d_atl_gen_3Dth_from_hycom.f90 ./UtilLib/schism_geometry.f90 ./UtilLib/extract_mod.f90 ./UtilLib/compute_zcor.f90 ./UtilLib/pt_in_poly_test.f90 $(LIB)

debug: compute_zcor.mod extract_mod.mod pt_in_poly_test.mod schism_geometry_mod.mod
	$(FC) $(OPT) -o stofs_3d_atl_gen_3Dth_from_hycom stofs_3d_atl_gen_3Dth_from_hycom.f90 ./UtilLib/schism_geometry.f90 ./UtilLib/extract_mod.f90 ./UtilLib/compute_zcor.f90 ./UtilLib/pt_in_poly_test.f90 $(LIB)

install: all
	mkdir build; cp stofs_3d_atl_gen_3Dth_from_hycom build/

compute_zcor.mod:
	$(FC) $(OPT) -c ./UtilLib/compute_zcor.f90

extract_mod.mod:
	$(FC) $(OPT) -c ./UtilLib/extract_mod.f90 $(LIB)

pt_in_poly_test.mod:
	$(FC) $(OPT) -c ./UtilLib/pt_in_poly_test.f90

schism_geometry_mod.mod:
	$(FC) $(OPT) -c ./UtilLib/schism_geometry.f90
clean:
	rm -f ./*.o ./*.mod ./stofs_3d_atl_gen_3Dth_from_hycom; rm -rf ./build


