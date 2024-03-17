"""
Collision avoidance using Nonlinear Model-Predictive Control

Adapted from Ashwin Bose 
https://github.com/atb033/multi_agent_path_planning/blob/master/decentralized/nmpc/nmpc.py
"""

from typing import Tuple
import numpy as np
from scipy.optimize import minimize, Bounds
import time


class Nmpc():

    def __init__(self, robot_radius, vmax, timestep=0.1, nmpc_timestep=0.3,  horizon_length=int(4)):
        self.timestep = timestep
        self.vmax = vmax

        # collision cost parameters
        # https://www.desmos.com/calculator/lu9hv6mq36
        # Assumes a agent radius of 0.25, we adjust scale to set actual agent radius
        self.Qc = 4.
        self.kappa = 6.
        self.static_kappa = 6.
        self.scale = robot_radius/0.25

        # nmpc parameters
        self.horizon_length = horizon_length
        self.nmpc_timestep = nmpc_timestep
        self.upper_bound = [(1/np.sqrt(2)) * self.vmax] * \
            self.horizon_length * 2
        self.lower_bound = [-(1/np.sqrt(2)) * self.vmax] * \
            self.horizon_length * 2
        self.goal = (0, 0)

        # num_timesteps, num_obstacles, Tuple array
        self.obstacle_position_history = None
        self.obstacle_position_history_timesteps = None

        # rectangle corners (x1, y1, x2, y2)
        self.static_obstacles = []

    def set_static_obstacles(self, static_obstacles):
        self.static_obstacles = static_obstacles

    def set_goal(self, goal: Tuple):
        self.goal = np.array(goal)

    def step(self, position, obstacle_positions: np.ndarray) -> Tuple:
        robot_state = np.array(position)

        obstacle_predictions = self.predict_obstacle_positions(
            obstacle_positions)
        xref = self.compute_xref(
            robot_state, self.goal, self.horizon_length, self.nmpc_timestep)
        # compute velocity using nmpc
        vel, velocity_profile = self.compute_velocity(
            robot_state, obstacle_predictions, xref)
        robot_state = self.update_state(robot_state, vel, self.timestep)

        return (vel[0], vel[1])

    def compute_velocity(self, robot_state, obstacle_predictions, xref):
        """
        Computes control velocity of the copter
        """
        # u0 = np.array([0] * 2 * self.horizon_length)
        u0 = np.random.rand(2*self.horizon_length)
        def cost_fn(u): return self.total_cost(
            u, robot_state, obstacle_predictions, xref)

        bounds = Bounds(self.lower_bound, self.upper_bound)

        res = minimize(cost_fn, u0, method='SLSQP', bounds=bounds)
        # velocity = res.x.reshape(-1, 2).mean(axis=0)
        velocity = res.x[:2]
        return velocity, res.x

    def compute_xref(self, start, goal, number_of_steps, timestep):
        dir_vec = (goal - start)
        norm = np.linalg.norm(dir_vec)
        if norm < self.vmax * timestep * number_of_steps:
            new_goal = goal
        else:
            dir_vec = dir_vec / norm
            new_goal = start + dir_vec * self.vmax * timestep * number_of_steps

        return np.linspace(start, new_goal, number_of_steps+1)[1:].reshape((2*number_of_steps))

    def total_cost(self, u, robot_state, obstacle_predictions, xref):
        x_robot = self.update_state(robot_state, u, self.nmpc_timestep)
        c1 = self.tracking_cost(x_robot, xref)
        c2 = self.total_collision_cost(x_robot, obstacle_predictions)
        total = c1 + c2
        return total

    def tracking_cost(self, x, xref):
        return np.linalg.norm(x-xref)

    def total_collision_cost(self, robot, obstacles):
        total_cost = 0
        for i in range(self.horizon_length):
            for j in range(len(obstacles)):
                obstacle = obstacles[j]
                rob = robot[2 * i: 2 * i + 2]
                obs = obstacle[2 * i: 2 * i + 2]
                total_cost += self.collision_cost(rob, obs)
            for static_obstacle in self.static_obstacles:
                rob = robot[2 * i: 2 * i + 2]
                distance = self.distance_point_to_rectangle(
                    rob, static_obstacle)
                cost = self.scale * self.Qc / \
                    (1 + np.exp(self.static_kappa *
                     distance / (self.scale/2)))
                total_cost += cost
        return total_cost

    def collision_cost(self, x0, x1):
        """
        Cost of collision between two robot_state
        """
        d = np.linalg.norm(x0 - x1)
        cost = self.scale * self.Qc / \
            (1 + np.exp(self.kappa * d / self.scale))
        return cost

    def distance_point_to_rectangle(self, point, rectangle):
        # Extracting coordinates
        x, y = point
        x1, y1, x2, y2 = rectangle

        # Finding rectangle boundaries
        min_x = min(x1, x2)
        max_x = max(x1, x2)
        min_y = min(y1, y2)
        max_y = max(y1, y2)

        # Finding distance to the closest edge
        if x < min_x:
            dx = min_x - x
        elif x > max_x:
            dx = x - max_x
        else:
            dx = 0

        if y < min_y:
            dy = min_y - y
        elif y > max_y:
            dy = y - max_y
        else:
            dy = 0

        # Calculating distance
        distance = np.sqrt(dx**2 + dy**2)
        return distance

    def predict_obstacle_positions(self, obstacle_positions: np.ndarray):
        obstacle_predictions = []
        for i in range(len(obstacle_positions)):
            if self.obstacle_position_history is not None:
                delta_time = time.time() - \
                    self.obstacle_position_history_timesteps[-1]
                obstacle_vel = (np.array(obstacle_positions[i]) - np.array(
                    self.obstacle_position_history[-1][i])) / delta_time
            else:
                obstacle_vel = np.array([0, 0])

            obstacle_position = np.array(obstacle_positions[i])
            u = np.vstack([np.eye(2)] * self.horizon_length) @ obstacle_vel
            obstacle_prediction = self.update_state(
                obstacle_position, u, self.nmpc_timestep)
            obstacle_predictions.append(obstacle_prediction)

        if self.obstacle_position_history is None:
            self.obstacle_position_history = np.array([obstacle_positions])
            self.obstacle_position_history_timesteps = np.array([time.time()])
        else:
            self.obstacle_position_history = np.append(
                self.obstacle_position_history, [obstacle_positions], axis=0)
            self.obstacle_position_history_timesteps = np.append(
                self.obstacle_position_history_timesteps, [time.time()], axis=0)

        return obstacle_predictions

    def update_state(self, x0, u, timestep):
        """
        Computes the states of the system after applying a sequence of control signals u on
        initial state x0
        """
        N = int(len(u) / 2)
        lower_triangular_ones_matrix = np.tril(np.ones((N, N)))
        kron = np.kron(lower_triangular_ones_matrix, np.eye(2))

        new_state = np.vstack([np.eye(2)] * int(N)) @ x0 + kron @ u * timestep

        return new_state
