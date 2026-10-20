import { useState, useCallback } from 'react';
import api from '../api';
import type { User } from '../types';

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);

  const login = useCallback(async (email: string, password: string) => {
    const { data } = await api.post('/users/login', { email, password });
    localStorage.setItem('token', data.access_token);
    setUser({ id: data.user_id, name: data.name, email });
    return data;
  }, []);

  const register = useCallback(async (name: string, email: string, password: string) => {
    const { data } = await api.post('/users', { name, email, password });
    const loginRes = await api.post('/users/login', { email, password });
    localStorage.setItem('token', loginRes.data.access_token);
    setUser({ id: data.id, name, email });
    return data;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('token');
    setUser(null);
  }, []);

  return { user, login, register, logout, isAuthenticated: !!user };
}   