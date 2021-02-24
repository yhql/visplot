
from itertools import cycle
import numpy as np
from vispy import scene
from vispy import color
from vispy import util 


class plot:
    """
    Fast plot of many large traces as a single object, using vispy. 
    """
    MAX_HL = 12 
    BG_DARK = "#222"
    LBL_POS_DEFAULTX = 170
    LBL_POS_DEFAULTY = 40
    LBL_SPACING = 16 

    def __init__(
        self, icurves, labels=None, clrmap="husl", parent=None
    ):
        """ 
        :param icurves: input curve or list of curves
        :param clrmap: (optional) what colormap name from vispy.colormap to use
        """
        self.canvas = scene.SceneCanvas(
            size=(1280, 900),
            position=(200, 200),
            keys="interactive",
            bgcolor=self.BG_DARK,
            parent=parent,
        )

        self.grid = self.canvas.central_widget.add_grid(spacing=0)
        self.view = self.grid.add_view(row=0, col=1, camera="panzoom")

        curves = np.array(icurves)

        self.shape_ = curves.shape

        if labels is not None:
            assert len(labels) == self.shape_[0]
            self.labels = labels
        else:
            self.labels = [f"0x{i:x}" for i in range(self.shape_[0])]

        if len(curves.shape) == 1:
            ## Single curve
            curves = np.array([icurves])

        nb_traces, size = curves.shape

        # the Line visual requires a vector of X,Y coordinates
        xy_curves = np.dstack((np.tile(np.arange(size), (nb_traces, 1)), curves))

        # Specify which points are connected
        # Start by connecting each point to its successor
        connect = np.empty((nb_traces * size - 1, 2), np.int32)
        connect[:, 0] = np.arange(nb_traces * size - 1)
        connect[:, 1] = connect[:, 0] + 1

        # Prevent vispy from drawing a line between the last point
        # of a curve and the first point of the next curve
        for i in range(size, nb_traces * size, size):
            connect[i - 1, 1] = i - 1

        self.colors = np.ones((nb_traces*size,3),dtype=np.float32)
        self.backup_colors = np.ones((nb_traces,3),dtype=np.float32)

        R_p = np.linspace(0.4,0.4,num=nb_traces)
        G_p = np.linspace(0.5,0.3,num=nb_traces)
        B_p = np.linspace(0.5,0.3,num=nb_traces)

        self.colors[:,0] = np.repeat(R_p,size)
        self.colors[:,1] = np.repeat(G_p,size)
        self.colors[:,2] = np.repeat(B_p,size)

        self.backup_colors[:,0] = R_p
        self.backup_colors[:,1] = G_p
        self.backup_colors[:,2] = B_p

        self.line = scene.Line(pos=xy_curves, color=self.colors, parent=self.view.scene, connect=connect)

        self.selected_lines = [] 
        self.hl_labels = []
        self.hl_colorset = cycle(color.get_colormap(clrmap)[np.linspace(0.0, 1.0, self.MAX_HL)])

        self.x_axis = scene.AxisWidget(orientation="bottom")
        self.y_axis = scene.AxisWidget(orientation="left")
        self.x_axis.stretch = (1, 0.05)
        self.y_axis.stretch = (0.05, 1)
        self.grid.add_widget(self.x_axis, row=1, col=1)
        self.grid.add_widget(self.y_axis, row=0, col=0)
        self.x_axis.link_view(self.view)
        self.y_axis.link_view(self.view)

        self.view.camera.set_range(x=(-1, size), y=(curves.min(), curves.max()))

        self.ctrl_pressed = False 
        self.shift_pressed = False 
        self.canvas.connect(self.on_key_press)
        self.canvas.connect(self.on_key_release)
        self.canvas.connect(self.on_mouse_press)
        self.canvas.connect(self.on_mouse_release)

        self.canvas.connect(self.on_mouse_move)
        
        self.canvas.show()
        if parent is None:
            self.canvas.app.run()

    def find_closest_line(self, x, y):
        # rx is the 'real x', which is an int
        rx = int(round(x))

        # Gather all segments within 2*N coordinates
        radius = 10
        tab = self.line.pos[:,rx-radius:rx+radius]

        f = np.array([x,y], dtype=np.float32)
        rmin = 100 
        imin = 0

        # Compute distance from click to all lines in the
        # vertical 20 pixels-wide segment around click 
        for i,s in enumerate(tab):
            for p in s:
                t = np.linalg.norm(p-f)
                if t < rmin:
                    rmin = t
                    imin = i
        
        # this is the index of the closest line
        return imin 

    def on_key_press(self, event):
        if event.key == 'Control':
            self.ctrl_pressed = True
        if event.key == 'Shift':
            self.shift_pressed = True

    def on_key_release(self, event):
        if event.key == 'Control':
            self.ctrl_pressed = False 
        if event.key == 'Shift':
            self.shift_pressed = False 

    def on_mouse_press(self, event):
        self.init_x, self.init_y = event.pos

    def on_mouse_move(self,event):
        if self.shift_pressed == True:
            if len(self.selected_lines) > 0:
                # map to screen displacement
                tr = self.canvas.scene.node_transform(self.view.scene)
                x,_,_,_ = tr.map(event.pos)
                init_x,_,_,_ = tr.map([self.init_x, self.init_y])
                delta_x = int(x - init_x)
                for l in self.selected_lines:
                    self.line.pos[l][:,1] = np.roll(self.line.pos[l][:,1],delta_x)
                self.init_x, self.init_y = event.pos
                self.canvas.update()

    def on_mouse_release(self, event):
        ## ignore release when moving traces
        if self.shift_pressed:
            return

        x,y = event.pos

        # if released more than 3 pixels away from click (i.e. dragging), ignore
        if not (abs(x-self.init_x)<3 and abs(y-self.init_y)<3):
            return

        # Find out actual coordinates in the graph
        tr = self.canvas.scene.node_transform(self.view.scene)
        x,y,_,_ = tr.map(event.pos)

        closest_line = self.find_closest_line(x,y)

        if self.ctrl_pressed:
            self.multiple_select(closest_line)
        else:
            self.single_select(closest_line)
                
    def _add_label(self, curve_index, new_color):
        new_label = scene.Text(f"{self.labels[curve_index]}", color=new_color, parent=self.canvas.scene)
        new_label.pos = self.LBL_POS_DEFAULTX, self.LBL_POS_DEFAULTY + self.LBL_SPACING * len(self.hl_labels)
        self.hl_labels.append((curve_index, new_label))

    def _del_label_from_curve_index(self, curve_index):
        idx = self._find_label_from_curve_index(curve_index)
        self.hl_labels[idx][1].parent = None
        del self.hl_labels[idx]

        ## redraw text items
        for i, lbl in enumerate(self.hl_labels[idx:]):
            lbl[1].pos = self.LBL_POS_DEFAULTX, self.LBL_POS_DEFAULTY + self.LBL_SPACING * (idx+i)

    def _find_label_from_curve_index(self, curve_index):
        return list(map(lambda x:x[0], self.hl_labels)).index(curve_index)

    def _set_curve_color(self,n, new_color):
        _, S = self.shape_
        a = n * S
        self.colors[a:a+S] = np.repeat(new_color.rgb, S, axis=0)

    def _restore_nth_curve_color(self,n):
        _, S = self.shape_
        nnx = n * S
        self.colors[nnx:nnx+S] = np.repeat([self.backup_colors[n]], S, axis=0)

    def single_select(self, curve_index):
        # Unselect previously highlighted curves
        for line in self.selected_lines:
            self._restore_nth_curve_color(line)

        # Delete labels
        for lbl in self.hl_labels:
            lbl[1].parent = None

        self.hl_labels = []

        # Display its index/label
        new_color = next(self.hl_colorset)               # Pick a new color
        self._add_label(curve_index, new_color)
        self.selected_lines = [curve_index]              # Add this curve to the selected batch
        self._set_curve_color(curve_index, new_color)    # Set its new color

        self.line.set_data(color=self.colors)            # Update colors

    def multiple_select(self, curve_index):
        if curve_index in self.selected_lines:
            # Clicked on already selected curve
            # so we cancel selection
            # - erase corresponding text
            # - restore original color of previously selected line
            self._del_label_from_curve_index(curve_index)
            self._restore_nth_curve_color(curve_index)
            self.selected_lines.remove(curve_index)
        else:
            N,S = self.shape_
            new_color = next(self.hl_colorset)
            self._add_label(curve_index, new_color)
            self.selected_lines.append(curve_index)
            self._set_curve_color(curve_index, new_color)
        
        self.line.set_data(color=self.colors)

if __name__ == "__main__":
    N = 50
    a = [i/10*np.sin(np.linspace(0.0+i/10,10.0+i/10,num=2000)) for i in range(N)]
    v = plot(a)
