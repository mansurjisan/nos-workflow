FC = ${COMP_F}


all: nos_ofs_create_tide_fac_schism.f90 tf_selfe.f90
	        $(FC) -o nos_ofs_create_tide_fac_schism  nos_ofs_create_tide_fac_schism.f90  tf_selfe.f90 
debug: nos_tide_fac_schism.f90 tf_selfe.f90
	        $(FC) -g -o nos_ofs_create_tide_fac_schism nos_ofs_create_tide_fac_schism.f90  tf_selfe.f90 
install: all
	cp -p  nos_ofs_create_tide_fac_schism ../../exec/


clean:
	rm -f ./*.o ./nos_ofs_create_tide_fac_schism

