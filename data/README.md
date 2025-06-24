# Data repository for benchmarks

## Introduction

As part of the EESSI framework, the ReFrame testing infrastructure is set up. Through this framework, both
the functionality and performance of libraries and applications can be verified on different architectures.
For some of the application benchmarks we need reasonably large input data. This github repository will host the 
different download scripts to pull this data into cvmfs and allow fast and consistent delivery during the benchmarks
without burdening the data hosting of the datasuppliers.  

## Layout

example for WRF Conus 12km dataset:
``` data/w/WRF/bench_12km ```
* data: data directory root
* w: hierarchy mapper
* WRF: application as identified in EasyConfigs
* bench_12km: benchmark name

## Download script

The download script is expected to download and expand the dataset into the same directory as the script, in such
way that the data is directly usable by the application. Additional steps that would require a copy such as unzipping \
or untarring should not be needed to run the benchmarks. 
