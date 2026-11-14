"""Reproducible tiny fixture and local helper configuration for the prototype."""
from pathlib import Path
import numpy as np
import DracoPy
HERE=Path(__file__).resolve().parent
root=HERE.parents[1]
points=np.array([[-1.,-1.,-1.],[1.,-1.,-1.],[1.,1.,-1.],[-1.,1.,-1.],[-1.,-1.,1.],[1.,-1.,1.],[1.,1.,1.],[-1.,1.,1.]])
faces=np.array([[0,1,2],[0,2,3],[4,6,5],[4,7,6],[0,4,5],[0,5,1],[2,6,7],[2,7,3],[0,3,7],[0,7,4],[1,5,6],[1,6,2]],dtype=np.uint32)
(HERE/'cube.drc').write_bytes(DracoPy.encode(points,faces))
(HERE/'build').mkdir(exist_ok=True)
(HERE/'build/preview.ini').write_text('[helper]\npython='+str(root/'.venv/Scripts/pythonw.exe')+'\nscript='+str(root/'explorer_preview/shell_preview.py')+'\n',encoding='utf-16')
