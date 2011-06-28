#!/usr/bin/env python
# -*- coding: utf-8 -*-

# 2011-06-28 14:40:44 

###############################################################################
# Copyright (c) 2010, Vadim Shlyakhov
#
#  Permission is hereby granted, free of charge, to any person obtaining a
#  copy of this software and associated documentation files (the "Software"),
#  to deal in the Software without restriction, including without limitation
#  the rights to use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of the Software, and to permit persons to whom the
#  Software is furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included
#  in all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
#  OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
#  THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#******************************************************************************

import sys
import os
import os.path
import glob
import shutil
import logging
import optparse
from PIL import Image
import pickle

from tiler_functions import *

class KeyboardInterruptError(Exception): 
    pass

def modify_htmls(src_dir, dest_dir):
    'adjusts destination gmaps.html and returns tile style (gmaps,TMS)'
    googlemaps='gmaps.html'
    #openlayers='openlayers.html'

    if not os.path.exists(os.path.join(dest_dir,googlemaps)):
        try:
            shutil.copy(os.path.join(src_dir,googlemaps),dest_dir)
            #shutil.copy(os.path.join(src_dir,openlayers),dest_dir)
        except: pass
    else:
        # get a list of zoom levels
        try:
            cwd=os.getcwd()
            os.chdir(dest_dir)
            dzooms=sorted([eval(i) for i in glob.glob('[0-9]*')])
        finally:
            os.chdir(cwd)
        zoom_min=dzooms[0]
        zoom_max=dzooms[-1]

        # get src bounds
        s=[ i for i in open(os.path.join(src_dir,googlemaps))
            if 'var mapBounds = new G.LatLngBounds' in i][0]
        num_str=re.sub('[^-,.0-9]*','',re.sub('\.Lat*','',s)) # leave only numbers there
        s_bounds=map(float,num_str.split(','))

        # get dest bounds
        s=[ i for i in open(os.path.join(dest_dir,googlemaps))
            if 'var mapBounds = new G.LatLngBounds' in i][0]
        num_str=re.sub('[^-,.0-9]*','',re.sub('\.Lat*','',s)) # leave only numbers there
        d_bounds=map(float,num_str.split(','))
        ld((s_bounds,d_bounds))
        if s_bounds[0] < d_bounds[0]: d_bounds[0]=s_bounds[0]
        if s_bounds[1] < d_bounds[1]: d_bounds[1]=s_bounds[1]
        if s_bounds[2] > d_bounds[2]: d_bounds[2]=s_bounds[2]
        if s_bounds[3] > d_bounds[3]: d_bounds[3]=s_bounds[3]
        ld(d_bounds)

        # write back modified googlemaps.html
        chart_name=os.path.split(dest_dir)[1]
        subs=[("(var mapBounds = new G.LatLngBounds).*;",
                "\\1( new G.LatLng(%f, %f), new G.LatLng(%f, %f));" % tuple(d_bounds)),
            ('(var mapMinZoom =).*;','\\1 %i;' % zoom_min),
            ('(var mapMaxZoom =).*;','\\1 %i;' % zoom_max),
            ('<title>.*</title>','<title>%s</title>' % chart_name),
            ('<h1>.*</h1>','<h1>%s</h1>' % chart_name)]
        re_sub_file(os.path.join(dest_dir,googlemaps), subs)

        # check if it's TMS type
        s=[ i for i in open(os.path.join(src_dir,googlemaps))
            if 'var tms_tiles' in i][0]
        tms_tiles= 'true' in s

        return tms_tiles

def transparency(img):
    'estimate transparency of an image'
    (r,g,b,a)=img.split()
    (a_min,a_max)=a.getextrema() # get min/max values for alpha channel
    return 1 if a_min == 255 else 0 if a_max == 0 else -1

class MergeSet:
    def __init__(self,src_dir,dest_dir):
        (self.src,self.dest)=(src_dir,dest_dir)
        if options.strip_src_ext:
            self.src=os.path.splitext(src)[0]
        if options.add_src_ext is not None:
            self.src+=options.add_src_ext
        pf(self.src+' ',end='')
        try:
            cwd=os.getcwd()
            os.chdir(self.src)
            self.src_lst=glob.glob('[0-9]*/*/*.png')
            self.max_zoom=max([int(i) for i in glob.glob('[0-9]*')])
        finally:
            os.chdir(cwd)
        ld(self.src_lst)
        
        # load cached tile transparency data if any
        self.src_transp=dict.fromkeys(self.src_lst,None)
        self.src_cache_path=os.path.join(self.src, 'merge-cache')
        try:
            self.src_transp.update(pickle.load(open(self.src_cache_path,'r')))
        except:
            ld("cache load failed")
        ld(repr(self.src_transp))
        
        # do the thing
        self.merge_dirs()

    def underlay(self,tile,src_path,src_raster,level):
        if level <= 0:
            return
        level -= 1
        (s,ext)=os.path.splitext(tile)
        (s,y)=os.path.split(s)
        (z,x)=os.path.split(s)
        (z,y,x)=map(int,(z,y,x))
        if z < self.max_zoom:
            return
        if self.tms_tiles:
            tiles_map=[
                (  0,128,128,256), (128,128,256,256),
                (  0,  0,128,128), (128,  0,256,128),
                ]
        else:
            tiles_map=[
                (  0,  0,128,128), (128,  0,256,128),
                (  0,128,128,256), (128,128,256,256),
                ]
        tiles_in=[(x*2,y*2), (x*2+1,y*2),
                  (x*2,y*2+1),(x*2+1,y*2+1)]
        for (src_xy,out_loc) in zip(tiles_in,tiles_map):
            dest_tile='%i/%i/%i%s' % (z+1,src_xy[0],src_xy[1],ext)
            dest_path=os.path.join(self.dest,dest_tile)
            if not os.path.exists(dest_path):
                continue
            dest_raster=Image.open(dest_path).convert("RGBA")
            if transparency(dest_raster) == 1: # lower tile is fully opaque
                continue
            if not src_raster: # check if opening was deferred
                src_raster=Image.open(src_path).convert("RGBA")
            out_raster=src_raster.crop(out_loc).resize((256,256),Image.BILINEAR)
            out_raster=Image.composite(dest_raster,out_raster,dest_raster)
            del dest_raster
            out_raster.save(dest_path)

            if options.debug:
                pf('%i'%level,end='')
            else:
                pf('#',end='')            
            self.underlay(dest_tile,dest_path,out_raster,level)
                
    def __call__(self,tile):
        '''called by map() to merge a source tile into the destination tile set'''
        try:
            src_path=os.path.join(self.src,tile)
            dest_tile=os.path.join(self.dest,tile)
            dpath=os.path.dirname(dest_tile)
            if not os.path.exists(dpath):
                try: # thread race safety
                    os.makedirs(dpath)
                except os.error: pass 
            src_raster=None
            transp=self.src_transp[tile]
            if transp == None: # transparency value not cached yet
                #pf('!',end='')
                src_raster=Image.open(src_path).convert("RGBA")
                transp=transparency(src_raster)
            if  transp == 0 : # fully transparent
                #pf('-',end='')
                #os.remove(src_path)
                pass
            elif transp == 1 or not os.path.exists(dest_tile): 
                # fully opaque or no destination tile exists yet
                #pf('>',end='')
                shutil.copy(src_path,dest_tile)
            else: # semitransparent, combine with destination (exists! see above)
                pf('+',end='')
                if not src_raster: 
                    src_raster=Image.open(src_path).convert("RGBA")
                dst_raster=Image.composite(src_raster,Image.open(dest_tile),src_raster)
                dst_raster.save(dest_tile)
            if options.underlay and transp != 0:
                self.underlay(tile,src_path,src_raster,options.underlay)
        except KeyboardInterrupt: # http://jessenoller.com/2009/01/08/multiprocessingpool-and-keyboardinterrupt/
            print 'got KeyboardInterrupt'
            raise KeyboardInterruptError()
        return (tile,transp) # send back transparency values for caching

    def upd_stat(self,stat):
        self.src_transp.update(dict(stat))
        try:
            pickle.dump(self.src_transp,open(self.src_cache_path,'w'))
        except:
            ld("cache save failed")
        pf('')

    def merge_dirs(self):
        self.tms_tiles=modify_htmls(self.src, self.dest)
        res=parallel_map(self,self.src_lst)
        self.upd_stat(res)

# MergeSet end

if __name__=='__main__':
    parser = optparse.OptionParser(
        usage="usage: %prog [--cut] [--dest-dir=DEST_DIR] <tile_dirs>... <target_dir>",
        version=version,
        description="")
    parser.add_option("-r", "--remove-dest", action="store_true",
        help='delete destination directory before merging')
    parser.add_option("-l", "--src-list", default=None,
        help='read source directories list from a file; if no destination is provided then name destination after list file without a suffix')
    parser.add_option("-s", "--strip-src-ext", action="store_true",
        help='strip extension suffix from a source parameter')
    parser.add_option("-x", "--add-src-ext", default=None,
        help='add extension suffix to a source parameter')
    parser.add_option('-u',"--underlay", type='int', default=0,
        help="underlay semitransparent tiles with a zoomed-in raster from a higher level")
    parser.add_option("-q", "--quiet", action="store_true")
    parser.add_option("-d", "--debug", action="store_true")
    parser.add_option("--nothreads", action="store_true",
        help="do not use multiprocessing")

    (options, args) = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if options.debug else 
        (logging.ERROR if options.quiet else logging.INFO))
        
    ld(options)

    if options.src_list:
        src_dirs=[i.rstrip('\n') for i in open(options.src_list,'r')]
        try:
            dest_dir=args[-1]
        except:
            dest_dir=os.path.splitext(options.src_list)[0]
    else:
        try:
            src_dirs=args[0:-1]
            dest_dir=args[-1]
        except:
            raise Exception("No source(s) or/and destination specified")

    if options.nothreads or options.debug:
        set_nothreads()

    if options.remove_dest: 
        shutil.rmtree(dest_dir,ignore_errors=True)
        
    if not os.path.exists(dest_dir):
        try:
            os.makedirs(dest_dir)
        except os.error: pass

    for src in src_dirs:
        if not (src.startswith("#") or src.strip() == ''): # ignore sources with names starting with "#" 
            MergeSet(src, dest_dir)

