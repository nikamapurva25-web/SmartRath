import axios from "axios";

const API = axios.create({
  baseURL: "http://127.0.0.1:8000/api",
  headers: {
    "Content-Type": "application/json",
  },
});

export const getEvents = async () => {
  const response = await API.get("/events");
  return response.data;
};

export const getStats = async () => {
  const response = await API.get("/stats");
  return response.data;
};

export const getDetections = async () => {
  const response = await API.get("/detections");
  return response.data;
};

export const getOdMatrix = async () => {
  const response = await API.get("/od-matrix");
  return response.data;
};

export default API;